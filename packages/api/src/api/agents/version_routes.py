"""버전 라우트(스펙 370) — 오픈(포인터 이동)·채택(pins 재freeze).

구 상태기계(draft/active/archived + 포크·되돌리기·프롬프트 스냅샷 갱신)는 폐기:
- 포크 → 없음(편집이 곧 다음 버전 작업 — 충돌 규칙은 crud_routes PUT).
- 되돌리기 → 예전 버전 오픈(activate)이 곧 롤백.
- prompt/refresh(스펙 161 promptStale) → 채택(adopt)이 전 블록으로 일반화.
오픈은 미래 평가 게이트(367-E: 점수·회수 임계)의 관문이다.
"""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_principal
from ..background import spawn
from ..block_versions import freeze_pins, resolve_pinned
from ..db import get_session
from ..models import AgentVersion, User
from ..ownership import assert_may_manage
from ..schemas import ActivateIn, AgentOut
from .guards import _enforce_ephemeral_boundary
from .helpers import _find_version, _load_agent, _reload_out, _today, scratch_target
from .routers import router


# ----------------------------- 오픈 (포인터 이동 + ever_opened) -----------------------------
@router.post("/{agent_id}/activate", response_model=AgentOut)
async def activate_version(
    agent_id: uuid.UUID,
    body: ActivateIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    """버전 오픈(스펙 370) — 라이브 포인터를 그 버전으로 옮기고 ever_opened를 영구 스탬프.

    롤백 = 예전 오픈 버전을 다시 오픈(같은 동사). head 컬럼(config/model/prompt/depth)은 오픈
    버전의 구체화 캐시 — prompt는 pin payload에서(불변), pin 부재 시 head 폴백(레거시)."""
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)

    target = _find_version(agent, body.version)
    if target is None:
        raise HTTPException(status_code=404, detail="version not found")
    if agent.active_version == body.version:
        raise HTTPException(status_code=400, detail="이미 오픈된 버전입니다")

    cfg = dict(target.config or {})
    _enforce_ephemeral_boundary(
        cfg
    )  # 스펙 237(codex #1) — 과거 버전 오픈도 "존재 불가" 불변식 유지
    target.ever_opened = True  # 오픈 이력 = 영구 불변 보호(스펙 370 충돌 규칙)
    agent.config = cfg
    agent.model = cfg["model"]
    agent.prompt = await _pinned_prompt_body(session, target, cfg)
    agent.history_depth = cfg["historyDepth"]
    agent.active_version = body.version
    agent.status = "online"

    await session.commit()
    # 자동 회귀(스펙 241, AgentOps B) — 새 버전이 서빙되는 순간 회귀 자산 자동 재실행(fire-and-forget:
    # 실패해도 오픈은 정상). 평가 게이트(367-E)가 추후 이 관문에 선다.
    from ..eval_routes import trigger_auto_regression

    spawn(trigger_auto_regression(agent.id, principal))
    return await _reload_out(session, agent.id)


async def _pinned_prompt_body(session: AsyncSession, vrow: AgentVersion, cfg: dict) -> str:
    """오픈 버전의 프롬프트 본문 — pin payload 우선(불변), 부재 시 head 해석 폴백(레거시·literal)."""
    from .helpers import resolve_prompt

    name = cfg.get("prompt") or ""
    payload = await resolve_pinned(session, vrow.pins, "prompt", name)
    if payload is not None:
        return payload.get("body", "")
    return await resolve_prompt(session, name)


# ----------------------------- 채택 (pins 재freeze — promptStale 후계) -----------------------------
@router.post("/{agent_id}/adopt", response_model=AgentOut)
async def adopt_block_versions(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    """블록 새 버전 채택(스펙 370 §4) — 오픈 버전 config 그대로, pins만 현재 head로 재freeze한
    스크래치를 만든다(충돌 규칙 공유). 오픈은 별도 명시 동작 — 채택이 서빙을 바꾸지 않는다."""
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(agent, principal, not_found_detail="agent not found")
    base = _find_version(agent, agent.active_version) if agent.active_version else None
    cfg = dict((base.config if base is not None else agent.config) or {})
    scratch, target_ver = scratch_target(agent)
    pins = await freeze_pins(session, cfg)
    if scratch is not None:
        scratch.version = target_ver
        scratch.config = cfg
        scratch.pins = pins
        scratch.note = f"블록 새 버전 채택 {_today()}"
    else:
        agent.versions.append(
            AgentVersion(
                version=target_ver,
                ever_opened=False,
                pins=pins,
                note=f"블록 새 버전 채택 {_today()}",
                config=cfg,
            )
        )
    await session.commit()
    return await _reload_out(session, agent.id)
