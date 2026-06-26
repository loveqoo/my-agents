"""에이전트 서비스 라우터 — 버전 관리 + A2A 노출 + 코드 에이전트 등록.

비동기 SQLAlchemy 2.0 + Pydantic v2. 모든 응답은 serializers.agent_to_out 경유.
agent.versions 는 lazy 관계라 async 세션 밖에서 로드하면 실패하므로,
조회/뮤테이션 후 항상 selectinload(Agent.versions) 로 eager-load 한다.
"""

import asyncio
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import memory
from .chat import resolve_agent_mem_cfg
from .db import get_session
from .models import Agent, AgentVersion, Persona
from .schemas import (
    ActivateIn,
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ExposeIn,
    RegisterCodeAgentIn,
    RegisterExternalAgentIn,
)
from . import agent_card, crypto
from .serializers import agent_to_out

router = APIRouter(prefix="/agents", tags=["agents"])


# ----------------------------- helpers -----------------------------
def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _new_agent_id() -> str:
    return "agt_" + secrets.token_hex(3)


def next_version(versions: list[AgentVersion]) -> str:
    """기존 'vN' 버전 문자열 중 최대 정수 + 1 → 'vN'. (UI 에이전트 전용)"""
    max_n = 0
    for v in versions:
        m = re.fullmatch(r"v(\d+)", v.version)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"v{max_n + 1}"


async def resolve_persona(session: AsyncSession, name: str) -> str:
    """이름으로 Persona 조회 → body 반환. 없으면 이름 그대로."""
    result = await session.execute(select(Persona).where(Persona.name == name))
    persona = result.scalar_one_or_none()
    return persona.body if persona is not None else name


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
    return agent_to_out(agent)


# 코드 에이전트 토큰은 암호화 저장(출력은 serializer가 마스킹). 원격 인증 시 복호화 사용.


def _find_version(agent: Agent, version: str) -> AgentVersion | None:
    return next((v for v in agent.versions if v.version == version), None)


# ----------------------------- 조회 -----------------------------
@router.get("", response_model=list[AgentOut])
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[AgentOut]:
    result = await session.execute(select(Agent).options(selectinload(Agent.versions)))
    return [agent_to_out(a) for a in result.scalars().all()]


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent_to_out(agent)


# ----------------------------- 생성 (UI) -----------------------------
@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentCreate, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    cfg = body.config.model_dump()
    agent = Agent(
        agent_id=_new_agent_id(),
        name=body.name,
        source="ui",
        model=body.config.model,
        persona=await resolve_persona(session, body.config.persona),
        history_depth=body.config.historyDepth,
        config=cfg,
        exposed={"a2a": False},
        status="idle",
        active_version=None,
    )
    agent.versions.append(
        AgentVersion(version="v1", status="draft", note="초기 초안", config=cfg)
    )
    session.add(agent)
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 편집 = 초안 저장 -----------------------------
@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    session: AsyncSession = Depends(get_session),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    cfg = body.config.model_dump()
    draft = next((v for v in agent.versions if v.status == "draft"), None)
    if draft is not None:
        draft.config = cfg
        draft.note = f"Edited {_today()}"
    else:
        agent.versions.append(
            AgentVersion(
                version=next_version(agent.versions),
                status="draft",
                note=f"Draft from {agent.active_version}",
                config=cfg,
            )
        )
    if body.name is not None:
        agent.name = body.name
    # 서빙 config/active_version 은 건드리지 않음.
    await session.commit()
    return await _reload_out(session, agent.id)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    await session.delete(agent)
    await session.commit()


# ----------------------------- 버전: 포크 -----------------------------
@router.post("/{agent_id}/versions", response_model=AgentOut)
async def fork_version(
    agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    # 단일 초안 불변식: 이미 초안이 있으면 새로 만들지 않는다(편집은 그 초안에 저장).
    if any(v.status == "draft" for v in agent.versions):
        raise HTTPException(status_code=400, detail="이미 초안이 있습니다 — 먼저 활성화하거나 편집하세요")

    agent.versions.append(
        AgentVersion(
            version=next_version(agent.versions),
            status="draft",
            note=f"{agent.active_version}에서 포크한 초안",
            config=dict(agent.config or {}),
        )
    )
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 버전: 활성화 -----------------------------
@router.post("/{agent_id}/activate", response_model=AgentOut)
async def activate_version(
    agent_id: uuid.UUID,
    body: ActivateIn,
    session: AsyncSession = Depends(get_session),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    target = _find_version(agent, body.version)
    if target is None:
        raise HTTPException(status_code=404, detail="version not found")
    # 이미 활성인 버전을 다시 활성화하는 것은 무의미 — 막는다.
    # (draft=게시, archived=롤백은 허용: UI VersionHistory의 "활성화" 동작과 일치)
    if target.status == "active":
        raise HTTPException(status_code=400, detail="이미 활성 버전입니다")

    for v in agent.versions:
        if v.status == "active":
            v.status = "archived"
    target.status = "active"

    cfg = dict(target.config or {})
    agent.config = cfg
    agent.model = cfg["model"]
    agent.persona = await resolve_persona(session, cfg["persona"])
    agent.history_depth = cfg["historyDepth"]
    agent.active_version = body.version
    agent.status = "online"

    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 버전: 되돌리기 -----------------------------
@router.post("/{agent_id}/revert", response_model=AgentOut)
async def revert_version(
    agent_id: uuid.UUID,
    body: ActivateIn,
    session: AsyncSession = Depends(get_session),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    target = _find_version(agent, body.version)
    if target is None:
        raise HTTPException(status_code=404, detail="version not found")

    # 가드: 다른 버전의 초안이 이미 존재하면 거부.
    other_draft = next(
        (v for v in agent.versions if v.status == "draft" and v.version != body.version),
        None,
    )
    if other_draft is not None:
        raise HTTPException(status_code=400, detail="이미 초안이 있습니다")

    if target.status == "active":
        # 승격 가능한 archived 버전(가장 최근)을 찾는다.
        archived = [v for v in agent.versions if v.status == "archived"]
        if not archived:
            raise HTTPException(status_code=400, detail="활성 버전이 유일합니다")
        promote = max(archived, key=lambda v: (v.created_at, v.version))
        promote.status = "active"
        cfg = dict(promote.config or {})
        agent.config = cfg
        agent.model = cfg["model"]
        agent.persona = await resolve_persona(session, cfg["persona"])
        agent.history_depth = cfg["historyDepth"]
        agent.active_version = promote.version

    target.status = "draft"
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- A2A 노출 -----------------------------
@router.put("/{agent_id}/expose", response_model=AgentOut)
async def expose_agent(
    agent_id: uuid.UUID,
    body: ExposeIn,
    session: AsyncSession = Depends(get_session),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    agent.exposed = {"a2a": body.a2a}
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 코드 에이전트 등록 -----------------------------
@router.post("/register", response_model=AgentOut, status_code=201)
async def register_code_agent(
    body: RegisterCodeAgentIn, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    cfg = {
        "model": body.model,
        "persona": body.persona,
        "memories": body.memories,
        "vectorTables": [],
        "permissions": body.permissions,
        "mcps": body.mcps,
        "historyDepth": body.historyDepth,
    }
    agent = Agent(
        agent_id=_new_agent_id(),
        name=body.name or body.repo or "코드 에이전트",
        source="code",
        model=body.model,
        persona=body.persona,
        history_depth=body.historyDepth,
        config=cfg,
        exposed={"a2a": False},
        status="online",
        endpoint=body.endpoint,
        token=crypto.encrypt(body.token),
        runtime=body.runtime,
        repo=body.repo,
        commit=body.commit,
        registered_at=_today(),
        last_sync="방금",
        active_version=body.commit or None,
    )
    if body.commit:
        agent.versions.append(
            AgentVersion(
                version=body.commit,
                status="active",
                note="Deploy · 등록 시 동기화",
                config=cfg,
            )
        )
    session.add(agent)
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 외부 에이전트 등록 (A2A 카드) -----------------------------
@router.post("/external", response_model=AgentOut, status_code=201)
async def register_external_agent(
    body: RegisterExternalAgentIn, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    """A2A Agent Card URL을 fetch·검증해 외부 에이전트로 등록(026, 1차).

    카드 스냅샷은 config["card"], 서비스 URL은 endpoint, 외부 호출 크레덴셜은 crypto.encrypt로
    token에 저장(코드 에이전트의 마스킹과 달리 2차 런타임 호출에서 복호 사용). 로컬 모델/메모리/
    MCP는 해석하지 않는다(비로컬). 실제 A2A 호출은 2차 스펙.
    """
    try:
        card = await agent_card.fetch_card(body.cardUrl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    cfg = {
        "model": "",  # 외부는 로컬 모델 미해석
        "persona": "",
        "memories": [],
        "vectorTables": [],
        "permissions": [],
        "mcps": [],
        "historyDepth": 10,
        "card": card,  # 등록 시점 카드 스냅샷(표시·검증 단일 소스)
    }
    agent = Agent(
        agent_id=_new_agent_id(),
        name=card.get("name") or "외부 에이전트",
        source="external",
        model="",
        persona="",
        history_depth=10,
        config=cfg,
        exposed={"a2a": False},  # 우리가 소비측(클라이언트) — 서버측 노출과 무관
        status="online",
        endpoint=card.get("url"),
        token=crypto.encrypt(body.token) if body.token else None,
        registered_at=_today(),
        last_sync="방금",
    )
    session.add(agent)
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 에이전트 전용 메모리 큐레이션 (스펙 029) -----------------------------
class AgentMemoryIn(BaseModel):
    text: str


async def _agent_mem_cfg(session: AsyncSession, agent_id: uuid.UUID):
    """에이전트 + agent_id 메모리용 mem_cfg 확보. 메모리 미가용이면 (agent, None)."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    mem_cfg = await resolve_agent_mem_cfg(session, agent)
    return agent, mem_cfg


async def _assert_owns(agent, mem_id: str, mem_cfg) -> None:
    """mem_id가 이 에이전트의 agent_id 기억에 속하는지 확인. 공유 pgvector라
    mem0 update/delete는 전역 id로 동작 → path agent_id로 소유권을 강제하지 않으면
    A의 큐레이션 화면에서 B(또는 임의 user_id/run_id) 행을 변조할 수 있다(스펙 029 비판리뷰)."""
    rows = await asyncio.to_thread(
        memory.list_memories, {"agent_id": agent.agent_id}, mem_cfg
    )
    if not any(r["id"] == mem_id for r in rows):
        raise HTTPException(status_code=404, detail="이 에이전트의 기억이 아닙니다")


@router.get("/{agent_id}/memory")
async def list_agent_memory(
    agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """에이전트 전용(agent_id) 기억 목록. 메모리 미가용이면 빈 목록(graceful)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    if mem_cfg is None:
        return []
    return await asyncio.to_thread(
        memory.list_memories, {"agent_id": agent.agent_id}, mem_cfg
    )


@router.post("/{agent_id}/memory", status_code=201)
async def add_agent_memory(
    agent_id: uuid.UUID, body: AgentMemoryIn, session: AsyncSession = Depends(get_session)
) -> dict:
    """관리자 저작 — agent_id-only·infer=False로 한 줄 사실을 저장(스펙 029)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    if mem_cfg is None:
        raise HTTPException(status_code=400, detail="이 에이전트는 장기 메모리가 활성화되지 않았습니다")
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="빈 메모리는 저장할 수 없습니다")
    await asyncio.to_thread(
        memory.add,
        {"agent_id": agent.agent_id},
        [{"role": "user", "content": text}],
        mem_cfg,
        False,  # infer=False — 정제된 사실 원문 저장
    )
    return {"ok": True}


@router.patch("/{agent_id}/memory/{mem_id}")
async def update_agent_memory(
    agent_id: uuid.UUID,
    mem_id: str,
    body: AgentMemoryIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """관리자 교정 — 기억 본문 수정(스펙 029)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    if mem_cfg is None:
        raise HTTPException(status_code=400, detail="이 에이전트는 장기 메모리가 활성화되지 않았습니다")
    await _assert_owns(agent, mem_id, mem_cfg)
    ok = await asyncio.to_thread(memory.update_memory, mem_id, body.text.strip(), mem_cfg)
    if not ok:
        raise HTTPException(status_code=400, detail="메모리 수정 실패")
    return {"ok": True}


@router.delete("/{agent_id}/memory/{mem_id}", status_code=204)
async def delete_agent_memory(
    agent_id: uuid.UUID, mem_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    """관리자 교정 — 기억 삭제(스펙 029)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    if mem_cfg is None:
        raise HTTPException(status_code=400, detail="이 에이전트는 장기 메모리가 활성화되지 않았습니다")
    await _assert_owns(agent, mem_id, mem_cfg)
    ok = await asyncio.to_thread(memory.delete_memory, mem_id, mem_cfg)
    if not ok:
        raise HTTPException(status_code=400, detail="메모리 삭제 실패")


# ----------------------------- 코드 에이전트 재동기화 -----------------------------
@router.post("/{agent_id}/resync", response_model=AgentOut)
async def resync_agent(
    agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    agent.last_sync = "방금"
    await session.commit()
    return await _reload_out(session, agent.id)
