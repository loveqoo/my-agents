"""공용 헬퍼 — 이름 규칙(스펙 148)·버전 문자열·페르소나 해석·로드/재직렬화.

agent.versions 는 lazy 관계라 async 세션 밖에서 로드하면 실패하므로,
조회/뮤테이션 후 항상 selectinload(Agent.versions) 로 eager-load 한다.
"""

import re
import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Agent, AgentVersion, Persona
from ..naming import slugify_name
from ..schemas import AgentOut
from ..serializers import agent_to_out


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _new_agent_id() -> str:
    return "agt_" + secrets.token_hex(3)


async def _dedupe_agent_name(session: AsyncSession, base: str) -> str:
    """자동 생성 식별 이름(복제·원격 유래)의 유니크 확보 — base, base-2, base-3…(스펙 148)."""
    rows = (
        (await session.execute(select(Agent.name).where(Agent.name.like(f"{base}%"))))
        .scalars()
        .all()
    )
    taken = set(rows)
    cand, i = base, 2
    while cand in taken:
        cand, i = f"{base}-{i}", i + 1
    return cand


async def _slugify_remote_agent(session: AsyncSession, agent: Agent) -> None:
    """원격 유래(A2A 카드·SDK 등록) 이름 자동 변환 — 원문은 설명(description)으로 보존, 식별 이름은
    slugify+유니크(스펙 148, 210). 우리가 짓는 이름이 아니므로 거부하지 않는다."""
    raw = agent.name
    agent.description = (agent.description or raw)[
        :200
    ]  # DB String(200) 정합(codex 148 — 원격 문자열 무clip)
    # base를 180자로 캡 — dedupe 접미(-N)가 붙어도 String(200)을 넘지 않게.
    agent.name = await _dedupe_agent_name(session, slugify_name(raw)[:180])


async def _commit_or_409(session: AsyncSession, detail: str) -> None:
    """이름 유니크 경합(동시 생성 레이스)을 500 대신 409로 접는다(스펙 148)."""
    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail) from err


def next_version(versions: list[AgentVersion]) -> str:
    """기존 'vN' 버전 문자열 중 최대 정수 + 1 → 'vN'. (UI 에이전트 전용)"""
    max_n = 0
    for version in versions:
        m = re.fullmatch(r"v(\d+)", version.version)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"v{max_n + 1}"


async def resolve_persona(session: AsyncSession, name: str) -> str:
    """이름으로 Persona 조회 → body 반환. 없으면 이름 그대로."""
    result = await session.execute(select(Persona).where(Persona.name == name))
    persona = result.scalar_one_or_none()
    return persona.body if persona is not None else name


async def _persona_bodies(session: AsyncSession) -> dict[str, str]:
    """{페르소나 이름: 현재 본문} 맵(스펙 161) — agent_to_out의 personaStale 계산용. 라우트가 1회 조회."""
    rows = (await session.execute(select(Persona))).scalars().all()
    return {p.name: p.body for p in rows}


async def _load_agent(session: AsyncSession, agent_pk: uuid.UUID) -> Agent | None:
    result = await session.execute(
        select(Agent).where(Agent.id == agent_pk).options(selectinload(Agent.versions))
    )
    return result.scalar_one_or_none()


async def _reload_out(session: AsyncSession, agent_pk: uuid.UUID) -> AgentOut:
    """commit 후 selectinload 로 재조회하여 직렬화."""
    agent = await _load_agent(session, agent_pk)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent_to_out(agent, await _persona_bodies(session))


def _find_version(agent: Agent, version: str) -> AgentVersion | None:
    return next((v for v in agent.versions if v.version == version), None)
