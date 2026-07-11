"""에이전트 CRUD 라우트 — 조회·운영 지표(스펙 244)·생성·복제(스펙 120)·편집·삭제."""

import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import current_principal
from ..chat import derive_pipeline_pool
from ..db import get_session
from ..models import Agent, AgentVersion, User
from ..ownership import assert_may_manage, may_manage, may_use_agent, owner_of
from ..schemas import AgentCreate, AgentOut, AgentUpdate
from ..serializers import agent_to_out
from .guards import _enforce_ephemeral_boundary, _enforce_tool_policy_gate
from .helpers import (
    _assert_valid_name,
    _commit_or_409,
    _dedupe_agent_name,
    _load_agent,
    _new_agent_id,
    _persona_bodies,
    _reload_out,
    _today,
    next_version,
    resolve_persona,
)
from .routers import router


# ----------------------------- 조회 -----------------------------
@router.get("", response_model=list[AgentOut])
async def list_agents(
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> list[AgentOut]:
    result = await session.execute(select(Agent).options(selectinload(Agent.versions)))
    rows = result.scalars().all()
    # 가시성(스펙 147): private(owner 있음)는 소유자·특권만 목록에서 본다(external은 항상).
    # 플레이그라운드도 이 목록을 쓰므로 자동 적용. admin/machine은 전부(관리 시야).
    from ..ownership import may_use_agent

    rows = [a for a in rows if may_use_agent(a, principal)]
    pbodies = await _persona_bodies(session)  # 스펙 161 — personaStale 계산용(1회 조회)
    outs = [agent_to_out(a, pbodies) for a in rows]
    for out in outs:  # 스펙 114 — 관리 가능 여부를 각 객체에 실어 UI가 버튼 표시를 파생
        out.can_manage = may_manage(out.owner_id, principal)
    return outs


class VersionOps(BaseModel):
    """버전 1개의 운영 지표(스펙 244) — 평가·자동 회귀·피드백."""

    evalRuns: int = 0
    lastScore: float | None = None
    lastRunAt: str | None = None
    autoRuns: int = 0  # 자동 회귀(env.trigger=activate) 런 수
    errorRuns: int = 0  # 실패 런 수(codex 244 #4 — 최근 성공 점수만 보이면 실패가 숨음)
    up: int = 0
    down: int = 0


class AgentOpsOut(BaseModel):
    """버전 운영 집계(스펙 244, AgentOps D) — "Version 하나가 운영 단위"의 데이터 면."""

    versions: dict[str, VersionOps]
    unversionedUp: int = 0  # 버전 미기록(242 이전) 피드백 — 정직한 분리
    unversionedDown: int = 0


def _version_ops(versions: dict[str, VersionOps], key: str) -> VersionOps:
    """versions 맵에서 key의 VersionOps를 얻는다(없으면 생성)."""
    if key not in versions:
        versions[key] = VersionOps()
    return versions[key]


async def _collect_eval_aggregates(
    session: AsyncSession, agent: Agent, versions: dict[str, VersionOps]
) -> None:
    """평가 런 집계(스펙 240 귀속·241 자동 회귀)와 버전별 최근 성공 점수를 versions에 채운다."""
    from sqlalchemy import case

    from ..models import EvalRun

    # 평가 집계 — SQL 전수(codex 244 #3: 최신 N개 순회는 조용한 과소집계 = no-silent-caps 위반).
    agg = (
        await session.execute(
            select(
                EvalRun.agent_version,
                func.count(EvalRun.id),
                func.sum(case((EvalRun.env["trigger"].astext == "activate", 1), else_=0)),
                func.sum(case((EvalRun.status == "error", 1), else_=0)),
            )
            .where(EvalRun.agent_pk == agent.id, EvalRun.agent_version.is_not(None))
            .group_by(EvalRun.agent_version)
        )
    ).all()
    for ver, total, auto, errs in agg:
        vo = _version_ops(versions, ver)
        vo.evalRuns = int(total)
        vo.autoRuns = int(auto or 0)
        vo.errorRuns = int(errs or 0)
    # 버전별 **최근 성공** 점수(DISTINCT ON) — 최신 런이 error여도 마지막 성공을 정직하게 표기
    # (UI는 errorRuns>0이면 실패 칩을 함께 노출 — codex 244 #4).
    last_ok = (
        await session.execute(
            select(EvalRun.agent_version, EvalRun.score, EvalRun.started_at)
            .where(
                EvalRun.agent_pk == agent.id,
                EvalRun.agent_version.is_not(None),
                EvalRun.status == "ok",
                EvalRun.score.is_not(None),
            )
            .distinct(EvalRun.agent_version)
            .order_by(EvalRun.agent_version, EvalRun.started_at.desc())
        )
    ).all()
    for ver, score, started_at in last_ok:
        vo = _version_ops(versions, ver)
        vo.lastScore = score
        vo.lastRunAt = started_at.isoformat() if started_at else None


async def _collect_feedback_aggregates(
    session: AsyncSession, agent: Agent, versions: dict[str, VersionOps]
) -> tuple[int, int]:
    """피드백 집계(스펙 209, 242 trace 귀속)를 versions에 채우고 버전 미기록 (up, down)을 반환."""
    from ..models import Message, MessageFeedback
    from ..models import Session as SessionRow

    # 피드백 집계 — feedback→message(trace.agentVersion)→session(agent_pk=이 에이전트).
    _ver_expr = Message.trace[
        "agentVersion"
    ].astext  # 식 재사용(두 번 쓰면 bind 파라미터가 갈라져 GROUP BY 불일치)
    fb = (
        await session.execute(
            select(_ver_expr, MessageFeedback.rating, func.count(MessageFeedback.id))
            .join(
                Message,
                (Message.id == MessageFeedback.message_pk)
                # codex 244 #1 — 중복 session_pk 불일치 행(보정/버그 유래) 방어: 메시지와 피드백의
                # 세션 일치를 조인에 강제(정상 경로는 항상 참, 불일치 행은 집계 제외).
                & (Message.session_pk == MessageFeedback.session_pk),
            )
            .join(SessionRow, SessionRow.id == MessageFeedback.session_pk)
            .where(SessionRow.agent_pk == agent.id)
            .group_by(_ver_expr, MessageFeedback.rating)
        )
    ).all()
    un_up = un_down = 0
    for ver, rating, cnt in fb:
        if ver:
            vo = _version_ops(versions, ver)
            if rating == "up":
                vo.up += int(cnt)
            else:
                vo.down += int(cnt)
        elif rating == "up":
            un_up += int(cnt)
        else:
            un_down += int(cnt)
    return un_up, un_down


@router.get("/{agent_id}/ops", response_model=AgentOpsOut)
async def agent_ops(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOpsOut:
    """버전별 운영 지표(스펙 244) — 평가(240 귀속)·자동 회귀(241)·피드백(209, 242 trace 귀속) 집계.

    게이트=상세와 동일(may_use_agent, 비가시 404-fold). 피드백의 버전 귀속은 대상 assistant 메시지의
    trace.agentVersion(242 이후 기록) — 미기록분은 unversioned로 정직하게 분리(과거를 아는 척 안 함)."""
    agent = await _load_agent(session, agent_id)
    if agent is None or not may_use_agent(agent, principal):
        raise HTTPException(status_code=404, detail="agent not found")
    if not may_manage(agent, principal):
        # 운영 지표=전 유저 피드백·평가 합산(codex 244 #2) — 관리자·소유자 전용(사용자는 대화만).
        raise HTTPException(
            status_code=403, detail="운영 지표는 이 에이전트를 관리할 수 있어야 합니다"
        )

    versions: dict[str, VersionOps] = {}
    await _collect_eval_aggregates(session, agent, versions)
    un_up, un_down = await _collect_feedback_aggregates(session, agent, versions)
    return AgentOpsOut(versions=versions, unversionedUp=un_up, unversionedDown=un_down)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None or not may_use_agent(agent, principal):
        # 사용 게이트(스펙 147, codex High#1) — 타인 private는 UUID를 알아도 미존재와 동일(404-fold,
        # 068: systemPrompt·config가 단건 응답에 실리므로 목록만 막으면 열람 우회).
        raise HTTPException(status_code=404, detail="agent not found")
    out = agent_to_out(agent, await _persona_bodies(session))
    out.can_manage = may_manage(out.owner_id, principal)  # 스펙 114
    return out


# ----------------------------- 생성 (UI) -----------------------------
@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentCreate,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    _assert_valid_name(body.name)  # 식별 이름 규칙(스펙 148) — 서버가 진실원
    cfg = body.config.model_dump()
    _enforce_tool_policy_gate(cfg, principal)
    _enforce_ephemeral_boundary(
        cfg
    )  # DB 쓰기 능력 금지(스펙 237)  # 완화는 admin만(스펙 177 P2 D4)
    await derive_pipeline_pool(
        cfg
    )  # 노드형 풀=노드 합집합 서버 파생(스펙 289 P2 — 폼 밖 입구도 안전)
    agent = Agent(
        agent_id=_new_agent_id(),
        name=body.name,
        description=(body.description or "").strip() or None,  # 설명(자유 표기, 스펙 210)
        source="ui",
        model=body.config.model,
        persona=await resolve_persona(session, body.config.persona),
        history_depth=body.config.historyDepth,
        config=cfg,
        exposed={"a2a": False},
        status="idle",
        active_version=None,
        owner_id=owner_of(principal),  # 생성 시 1회 스탬프(스펙 112, 069)
    )
    agent.versions.append(AgentVersion(version="v1", status="draft", note="초기 초안", config=cfg))
    session.add(agent)
    await _commit_or_409(session, "같은 식별 이름의 에이전트가 이미 있습니다.")
    return await _reload_out(session, agent.id)


# ----------------------------- 복제 (저마찰 재사용, 스펙 120) -----------------------------
@router.post("/{agent_id}/clone", response_model=AgentOut, status_code=201)
async def clone_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    """기존 에이전트 설정을 새 **ui 초안**으로 복사(행위 재사용 — '이거랑 비슷한 거 하나 더'). 복제는
    **읽기+새 생성**이라 원본 *관리 권한 불요*(가시하면 복제 가능 — 사용≠관리, 스펙 112). 소유권은
    **복제자**에게 스탬프(원본 소유자 승계 금지 — 069 no-takeover). 미존재/미가시 원본은 404-fold."""
    src = await _load_agent(session, agent_id)
    if src is None or not may_use_agent(src, principal):
        # codex High#2 — 타인 private를 복제하면 설정(페르소나·능력)이 내 소유로 유출되고
        # 복제본 채팅으로 사용 게이트가 무력화된다. "가시하면 복제"의 가시=may_use(147 이후).
        raise HTTPException(status_code=404, detail="agent not found")
    cfg = dict(src.config or {})
    cfg.pop(
        "card", None
    )  # 외부 등록 스냅샷은 복사 안 함(ui 복제=행위 설정만; endpoint/token은 Agent 컬럼이라 애초 미복사)
    _enforce_tool_policy_gate(cfg, principal)
    _enforce_ephemeral_boundary(
        cfg
    )  # DB 쓰기 능력 금지(스펙 237)  # 완화 정책 복제도 admin만(스펙 177 P2 D4)
    clone = Agent(
        agent_id=_new_agent_id(),
        # 식별 이름은 규칙 준수+유니크로 자동 생성(스펙 217: 영소문자·숫자·대시만 — 접미는 영문 '-copy'),
        # 사람용 표기는 설명에(스펙 148, 210). base 캡=접미 여유.
        name=await _dedupe_agent_name(session, f"{src.name[:180]}-copy"),
        description=f"{src.description or src.name} (복사본)"[:200],
        source="ui",
        model=cfg.get("model") or src.model,
        persona=await resolve_persona(session, cfg.get("persona") or ""),
        history_depth=cfg.get("historyDepth") or src.history_depth,
        config=cfg,
        exposed={"a2a": False},
        status="idle",
        active_version=None,
        owner_id=owner_of(principal),  # 복제자가 소유(스펙 112·069 — 원본 소유자 승계 안 함)
    )
    clone.versions.append(
        AgentVersion(version="v1", status="draft", note=f"복제: {src.name}", config=cfg)
    )
    session.add(clone)
    await _commit_or_409(session, "같은 식별 이름의 에이전트가 이미 있습니다.")
    return await _reload_out(session, clone.id)


def _preserve_impl(body: AgentUpdate, agent: Agent, draft: AgentVersion | None, cfg: dict) -> None:
    """요청에 impl 미명시면 편집 베이스(초안→활성 config)의 impl을 cfg에 이어받는다.

    impl(스펙 085 SDK 런타임 키)은 편집 폼이 아직 안 보내므로(SPA 미배선), 요청에 명시되지
    않으면 기존 값을 보존한다 — 안 그러면 Pydantic 기본 None이 덮어써 편집→활성화가 커스텀
    에이전트를 DefaultUiAgent로 silent 되돌린다(codex 적대 리뷰 F1). 명시적으로 보내면(클리어 포함)
    그 값 존중."""
    if "impl" not in body.config.model_fields_set:
        base = (draft.config if draft is not None else None) or dict(agent.config or {})
        cfg["impl"] = base.get("impl")


# ----------------------------- 편집 = 초안 저장 -----------------------------
@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)

    cfg = body.config.model_dump()
    _enforce_tool_policy_gate(cfg, principal)
    _enforce_ephemeral_boundary(
        cfg
    )  # DB 쓰기 능력 금지(스펙 237)  # 완화는 admin만(스펙 177 P2 D4)
    draft = next((v for v in agent.versions if v.status == "draft"), None)
    _preserve_impl(body, agent, draft, cfg)
    # 노드형 풀=노드 합집합 서버 파생(스펙 289 P2) — impl 보존 **뒤**에 호출(미명시 impl이 pipeline로
    # 확정된 뒤라야 파생 게이트가 맞는다).
    await derive_pipeline_pool(cfg)
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
    if body.name is not None and body.name != agent.name:
        _assert_valid_name(body.name)  # 식별 이름 변경도 규칙(스펙 148)
        agent.name = body.name
    if body.description is not None:
        agent.description = body.description.strip() or None  # ""=설명 비우기
    # 서빙 config/active_version 은 건드리지 않음.
    await _commit_or_409(session, "같은 식별 이름의 에이전트가 이미 있습니다.")
    return await _reload_out(session, agent.id)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> None:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)
    await session.delete(agent)
    await session.commit()
