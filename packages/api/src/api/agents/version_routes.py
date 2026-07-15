"""버전 라우트 — 포크·활성화·프롬프트 스냅샷 갱신(스펙 161)·되돌리기."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent.runtime import is_first_party

from ..auth import current_principal
from ..background import spawn
from ..db import get_session
from ..models import Agent, AgentVersion, User
from ..ownership import assert_may_manage
from ..schemas import ActivateIn, AgentOut
from .guards import _enforce_ephemeral_boundary
from .helpers import _find_version, _load_agent, _reload_out, next_version, resolve_prompt
from .routers import router


# ----------------------------- 버전: 포크 -----------------------------
@router.post("/{agent_id}/versions", response_model=AgentOut)
async def fork_version(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)

    # 단일 초안 불변식: 이미 초안이 있으면 새로 만들지 않는다(편집은 그 초안에 저장).
    if any(v.status == "draft" for v in agent.versions):
        raise HTTPException(
            status_code=400, detail="이미 초안이 있습니다 — 먼저 활성화하거나 편집하세요"
        )

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
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)

    target = _find_version(agent, body.version)
    if target is None:
        raise HTTPException(status_code=404, detail="version not found")
    # 이미 활성인 버전을 다시 활성화하는 것은 무의미 — 막는다.
    # (draft=게시, archived=롤백은 허용: UI VersionHistory의 "활성화" 동작과 일치)
    if target.status == "active":
        raise HTTPException(status_code=400, detail="이미 활성 버전입니다")

    for version in agent.versions:
        if version.status == "active":
            version.status = "archived"
    target.status = "active"

    cfg = dict(target.config or {})
    _enforce_ephemeral_boundary(
        cfg
    )  # 스펙 237(codex #1) — 과거 버전 승격도 "존재 불가" 불변식 유지
    agent.config = cfg
    agent.model = cfg["model"]
    agent.prompt = await resolve_prompt(session, cfg["prompt"])
    agent.history_depth = cfg["historyDepth"]
    agent.active_version = body.version
    agent.status = "online"

    await session.commit()
    # 자동 회귀(스펙 241, AgentOps B) — 새 버전이 서빙되는 순간 회귀 자산 자동 재실행(fire-and-forget:
    # 실패해도 활성화는 정상). 결과는 평가 이력에 "자동 회귀 · vN"으로.
    from ..eval_routes import trigger_auto_regression

    spawn(trigger_auto_regression(agent.id, principal))
    return await _reload_out(session, agent.id)


# ----------------------------- 프롬프트 스냅샷 갱신(스펙 161) -----------------------------
@router.post("/{agent_id}/prompt/refresh", response_model=AgentOut)
async def refresh_prompt(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    """에이전트의 프롬프트 스냅샷을 현재 원본으로 재해석(스펙 161). config.prompt 이름은 그대로,
    `agent.prompt`(서빙 본문)만 in-place 갱신 → 새 버전 안 만듦(활성화 재해석 경로와 동일 동사).
    스냅샷 복사는 유지(영향도 격리)하되 사용자가 명시적으로 눌러야 반영 = 통제된 전파."""
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)
    if not is_first_party(agent.source):
        # 외부/A2A는 로컬 프롬프트가 없다(카드 스냅샷) — 갱신 대상 아님.
        raise HTTPException(status_code=400, detail="외부 에이전트는 프롬프트 갱신 대상이 아닙니다")
    cfg = dict(agent.config or {})
    agent.prompt = await resolve_prompt(session, cfg.get("prompt") or "")
    await session.commit()
    return await _reload_out(session, agent.id)


async def _promote_latest_archived(session: AsyncSession, agent: Agent) -> None:
    """가장 최근 archived 버전을 active로 승격해 서빙 config를 되돌린다(없으면 400)."""
    archived = [v for v in agent.versions if v.status == "archived"]
    if not archived:
        raise HTTPException(status_code=400, detail="활성 버전이 유일합니다")
    promote = max(archived, key=lambda v: (v.created_at, v.version))
    promote.status = "active"
    cfg = dict(promote.config or {})
    _enforce_ephemeral_boundary(cfg)  # 스펙 237(codex #1) — 아카이브 승격도 동일 불변식
    agent.config = cfg
    agent.model = cfg["model"]
    agent.prompt = await resolve_prompt(session, cfg["prompt"])
    agent.history_depth = cfg["historyDepth"]
    agent.active_version = promote.version


# ----------------------------- 버전: 되돌리기 -----------------------------
@router.post("/{agent_id}/revert", response_model=AgentOut)
async def revert_version(
    agent_id: uuid.UUID,
    body: ActivateIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)

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

    promoted = False  # 승격 분기 여부(스펙 241) — 서빙이 실제로 바뀐 경우만 자동 회귀
    if target.status == "active":
        await _promote_latest_archived(session, agent)
        promoted = True

    target.status = "draft"
    await session.commit()
    if promoted:
        # 서빙 버전이 실제로 바뀐 경우만 자동 회귀(스펙 241) — 단순 draft 강등은 서빙 불변이라 제외.
        from ..eval_routes import trigger_auto_regression

        spawn(trigger_auto_regression(agent.id, principal))
    return await _reload_out(session, agent.id)
