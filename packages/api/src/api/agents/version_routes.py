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
    # 평가 게이트(스펙 372=367-E) — 스크래치(미오픈) 첫 오픈만. 롤백(ever_opened)은 면제(개발자 확정:
    # 긴급 롤백을 게이트가 막으면 사고 대응이 잠긴다). 우회 플래그 없음 — 급하면 설정에서 임계를
    # 낮추는 명시 행위로만(감사 가능).
    if not target.ever_opened and agent.source == "ui":
        blocked = await _eval_gate_reason(session, agent.id, body.version)
        if blocked:
            raise HTTPException(status_code=400, detail=blocked)

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

    # 오픈 이벤트의 버전을 명시 관통(스펙 399 버전 핀 완성형 — codex 적대: 태스크 실행 전 재오픈이
    # 끼면 태스크가 나중 active를 캡처하는 race, 이벤트 버전을 인자로 고정).
    spawn(trigger_auto_regression(agent.id, principal, opened_version=body.version))
    return await _reload_out(session, agent.id)


async def _eval_gate_reason(session: AsyncSession, agent_pk: uuid.UUID, version: str) -> str | None:
    """평가 게이트 판정(스펙 372) — 통과면 None, 미달이면 사유(긍정형: 무엇이 되면 열리는가).

    회수 = 그 버전의 성공(status=ok·score 보유) 평가 런 수, 점수 = 그 런들의 **평균**(개발자 확정 —
    우연한 1회 고/저점에 안 덩샘). 임계는 전역 설정(app_settings) — 둘 다 0이면 게이트 꺼짐."""
    from sqlalchemy import func, select

    from ..app_settings import get_setting
    from ..models import EvalRun

    min_runs = await get_setting("eval_gate_min_runs")
    min_score = await get_setting("eval_gate_min_score")
    if not min_runs and not min_score:
        return None  # 게이트 꺼짐(기본) — 무회귀
    runs, avg_score = (
        await session.execute(
            select(func.count(EvalRun.id), func.avg(EvalRun.score)).where(
                EvalRun.agent_pk == agent_pk,
                EvalRun.agent_version == version,
                EvalRun.status == "ok",
                EvalRun.score.is_not(None),
            )
        )
    ).one()
    runs = int(runs or 0)
    avg_score = float(avg_score) if avg_score is not None else None
    # 경계값 부동소수 가드 — 평균이 이진 표현상 0.7999…로 떨어져도 80% 임계를 통과해야 한다
    # (verify_372가 정확 경계(0.9+0.5+1.0)/3=0.8을 회귀 핀으로 고정).
    ok = runs >= int(min_runs) and (
        float(min_score) <= 0 or (avg_score or 0) + 1e-9 >= float(min_score)
    )
    if ok:
        return None
    now_score = f"평균 {avg_score * 100:.0f}%" if avg_score is not None else "점수 없음"
    return (
        f"평가 게이트: 현재 성공 평가 {runs}회·{now_score} — "
        f"{int(min_runs)}회 이상·평균 {float(min_score) * 100:.0f}% 이상이면 오픈할 수 있습니다. "
        f"(에이전트 상세·평가 화면에서 이 버전(v{version.lstrip('v')})을 지정해 평가를 돌리세요)"
    )


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
