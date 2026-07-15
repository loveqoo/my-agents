"""에이전트 전용 메모리 큐레이션 라우트 (스펙 029) — 목록·페이지(127)·회상 시험(084)·저작·교정."""

import asyncio
import uuid

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import memory
from ..auth import current_principal
from ..chat import resolve_agent_mem_cfg
from ..db import get_session
from ..models import Agent, User
from ..ownership import assert_may_manage, may_use_agent
from ..schemas import (
    MemoryHit,
    MemoryPageItem,
    MemoryPageOut,
    MemorySearchDiag,
    MemorySearchIn,
    MemorySearchOut,
)
from .routers import router


class AgentMemoryIn(BaseModel):
    text: str


async def _agent_mem_cfg(
    session: AsyncSession, agent_id: uuid.UUID, principal: User | str | None = None
) -> tuple[Agent, dict | None]:
    """에이전트 + agent_id 메모리용 mem_cfg 확보. 메모리 미가용이면 (agent, None).
    principal 전달 시 사용 게이트(스펙 147, codex High#3) — 타인 private의 기억 읽기/검색 차단
    (쓰기/삭제는 assert_may_manage가 이미 막지만 읽기가 무게이트였다). 404-fold."""
    agent = await session.get(Agent, agent_id)
    if agent is None or (principal is not None and not may_use_agent(agent, principal)):
        raise HTTPException(status_code=404, detail="agent not found")
    mem_cfg = await resolve_agent_mem_cfg(session, agent)
    return agent, mem_cfg


async def _assert_owns(agent: Agent, mem_id: str, mem_cfg: dict | None) -> None:
    """mem_id가 이 에이전트의 agent_id 기억에 속하는지 확인. 공유 pgvector라
    mem0 update/delete는 전역 id로 동작 → path agent_id로 소유권을 강제하지 않으면
    A의 큐레이션 화면에서 B(또는 임의 user_id/run_id) 행을 변조할 수 있다(스펙 029 비판리뷰)."""
    rows = await asyncio.to_thread(memory.list_memories, {"agent_id": agent.agent_id}, mem_cfg)
    if not any(r["id"] == mem_id for r in rows):
        raise HTTPException(status_code=404, detail="이 에이전트의 기억이 아닙니다")


@router.get("/{agent_id}/memory")
async def list_agent_memory(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> list[dict]:
    """에이전트 전용(agent_id) 기억 목록. 메모리 미가용이면 빈 목록(graceful)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id, principal)
    if mem_cfg is None:
        return []
    return await asyncio.to_thread(memory.list_memories, {"agent_id": agent.agent_id}, mem_cfg)


@router.get("/{agent_id}/memory/page", response_model=MemoryPageOut)
async def page_agent_memory(
    agent_id: uuid.UUID,
    q: str | None = Query(None, max_length=500),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> MemoryPageOut:
    """에이전트 기억 페이지 목록(스펙 127) — 서버 페이지네이션 + 부분일치(q).

    소유권: 사용 게이트(147) + 스코프(agent_id)는 백엔드가 SQL WHERE로.
    미구성 → enabled=False. 백엔드 실패 → 502(빈 목록 위장 금지, learning 125)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id, principal)
    try:
        page = await asyncio.to_thread(
            memory.list_page, {"agent_id": agent.agent_id}, q, mem_cfg, limit, offset
        )
    except Exception as exc:
        secrets = memory._cfg_secrets(mem_cfg)
        raise HTTPException(
            status_code=502,
            detail="메모리 목록 조회 실패: " + memory._sanitize(exc, secrets=secrets),
        ) from exc
    if page is None:
        return MemoryPageOut(items=[], total=0, limit=limit, offset=offset, enabled=False)
    return MemoryPageOut(
        items=[MemoryPageItem(**it) for it in page["items"]],
        total=page["total"],
        limit=limit,
        offset=offset,
        enabled=True,
    )


@router.post("/{agent_id}/memory/search", response_model=MemorySearchOut)
async def search_agent_memory(
    agent_id: uuid.UUID,
    body: MemorySearchIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> MemorySearchOut:
    """회상 시험(스펙 084) — 챗과 동일한 공유 코어 `memory.search`로 agent_id 스코프 회상.

    사용 게이트(147) 적용. 스코프 dict가 mem0 filter로 들어가 이 에이전트 기억만 로드.
    미구성이면 enabled=False·빈결과."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id, principal)
    # recall_diag(스펙 125): 미가용 사유(미설정/초기화실패/검색예외)를 구조화(예외 안 던짐).
    # enabled=backend_ready로 기존 계약 유지(깨진 백엔드를 "회상 0건"으로 위장 안 함, 084 P2a).
    d = await asyncio.to_thread(
        memory.recall_diag, {"agent_id": agent.agent_id}, body.query, mem_cfg, body.limit
    )
    results = [MemoryHit(**h) for h in d["results"]]
    return MemorySearchOut(
        query=body.query,
        limit=body.limit,
        enabled=d["backend_ready"],
        results=results,
        diag=MemorySearchDiag(
            configured=d["configured"],
            backendReady=d["backend_ready"],
            embedderModel=d["embedder_model"],
            llmModel=d["llm_model"],
            error=d["error"],
            scope=agent.agent_id,
            count=len(results),
            stored=d.get("stored"),  # 스코프 저장 건수(스펙 158) — 유저 라우트와 동형(codex Med)
        ),
    )


@router.post("/{agent_id}/memory", status_code=201)
async def add_agent_memory(
    agent_id: uuid.UUID,
    body: AgentMemoryIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> dict:
    """관리자 저작 — agent_id-only·infer=False로 한 줄 사실을 저장(스펙 029)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112, codex P1)
    if mem_cfg is None:
        raise HTTPException(
            status_code=400, detail="이 에이전트는 장기 메모리가 활성화되지 않았습니다"
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="빈 메모리는 저장할 수 없습니다")
    stored = await asyncio.to_thread(
        memory.add,
        {"agent_id": agent.agent_id},
        [{"role": "user", "content": text}],
        mem_cfg,
        False,  # infer=False — 정제된 사실 원문 저장
    )
    if not stored:  # add는 임베더 장애 등을 삼켜 []를 돌린다 — 저장 실패를 ok로 위장 금지(스펙 357 P2)
        raise HTTPException(status_code=502, detail="메모리 저장에 실패했습니다(백엔드 오류)")
    return {"ok": True}


@router.patch("/{agent_id}/memory/{mem_id}")
async def update_agent_memory(
    agent_id: uuid.UUID,
    mem_id: str,
    body: AgentMemoryIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> dict:
    """관리자 교정 — 기억 본문 수정(스펙 029)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112, codex P1)
    if mem_cfg is None:
        raise HTTPException(
            status_code=400, detail="이 에이전트는 장기 메모리가 활성화되지 않았습니다"
        )
    await _assert_owns(agent, mem_id, mem_cfg)
    ok = await asyncio.to_thread(memory.update_memory, mem_id, body.text.strip(), mem_cfg)
    if not ok:
        raise HTTPException(status_code=400, detail="메모리 수정 실패")
    return {"ok": True}


@router.delete("/{agent_id}/memory/{mem_id}", status_code=204)
async def delete_agent_memory(
    agent_id: uuid.UUID,
    mem_id: str,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> None:
    """관리자 교정 — 기억 삭제(스펙 029)."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112, codex P1)
    if mem_cfg is None:
        raise HTTPException(
            status_code=400, detail="이 에이전트는 장기 메모리가 활성화되지 않았습니다"
        )
    await _assert_owns(agent, mem_id, mem_cfg)
    ok = await asyncio.to_thread(memory.delete_memory, mem_id, mem_cfg)
    if not ok:
        raise HTTPException(status_code=400, detail="메모리 삭제 실패")
