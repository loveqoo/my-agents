"""원격 라우트 — 코드 에이전트 등록·통합 연결(스펙 057)·외부 등록(deprecated)·재동기화(스펙 081)."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import agent_card, crypto, net_guard
from ..auth import current_principal
from ..db import get_session
from ..models import Agent, AgentVersion, User
from ..naming import slugify_name
from ..ownership import assert_may_manage, owner_of
from ..schemas import AgentOut, ConnectAgentIn, RegisterCodeAgentIn, RegisterExternalAgentIn
from .card_builder import _build_code_agent_from_card, _build_external_agent, _clip, _norm_endpoint
from .helpers import (
    _commit_or_409,
    _dedupe_agent_name,
    _find_version,
    _load_agent,
    _new_agent_id,
    _reload_out,
    _slugify_remote_agent,
    _today,
)
from .routers import router


# ----------------------------- 코드 에이전트 등록 -----------------------------
@router.post("/register", response_model=AgentOut, status_code=201)
async def register_code_agent(
    body: RegisterCodeAgentIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    # endpoint를 절대 http(s)로 정규화(스펙 060, 일관성). SDK 직접 등록이라 base는 없다 — 스킴 없는
    # host:port는 http:// 전치, 절대화 불가(빈 값·비-http 스킴)면 등록 시점에 400(채팅서 늦게 안 깸).
    try:
        endpoint = net_guard.normalize_http_url(body.endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = {
        "model": body.model,
        "persona": body.persona,
        "memories": body.memories,
        "vectorTables": [],
        "mcps": body.mcps,
        "historyDepth": body.historyDepth,
    }
    raw_name = (body.name or body.repo or "코드 에이전트")[:200]
    agent = Agent(
        agent_id=_new_agent_id(),
        # 원격 유래(SDK 등록명) — 거부 대신 자동 변환, 원문은 설명으로(스펙 148, 210). base 180자 캡=접미 여유.
        name=await _dedupe_agent_name(session, slugify_name(raw_name)[:180]),
        description=raw_name,
        source="code",
        model=body.model,
        persona=body.persona,
        history_depth=body.historyDepth,
        config=cfg,
        exposed={"a2a": False},
        status="online",
        endpoint=endpoint,
        token=crypto.encrypt(body.token),
        runtime=body.runtime,
        repo=body.repo,
        commit=body.commit,
        registered_at=_today(),
        last_sync="방금",
        active_version=body.commit or None,
        owner_id=owner_of(principal),  # 생성 시 1회 스탬프(스펙 112)
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
    await _commit_or_409(session, "같은 식별 이름의 에이전트가 이미 있습니다.")
    return await _reload_out(session, agent.id)


# ----------------------------- 통합 연결 (스펙 057 — A2A 단일화) -----------------------------
@router.post("/connect", response_model=AgentOut, status_code=201)
async def connect_agent(
    body: ConnectAgentIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    """원격 에이전트 연결 — URL 하나로 A2A 카드를 fetch해 provenance 자동분류(스펙 057).

    카드에 my-agents 확장(x-my-agents.manifest)이 있으면 우리가 SDK로 배포한 제1자(source=code,
    매니페스트·배포 메타 보유), 없으면 제3자 A2A(source=external, 불투명). 둘 다 런타임은 A2A 하나.
    SSRF 가드는 fetch_card·probe_endpoint가 각각 guard_url 선행(044/055).
    """
    try:
        card = await agent_card.fetch_card(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 카드 published ≠ 실행 엔드포인트 live(045 #2). 도달 실패해도 등록 허용, status만 정직하게.
    live = await agent_card.probe_endpoint(card.get("url"))
    ext = agent_card.extract_my_agents(card)
    if ext is not None:
        agent = _build_code_agent_from_card(card, ext, body.token, live, body.url)
    else:
        agent = _build_external_agent(card, body.token, live, body.url)
    agent.owner_id = owner_of(principal)  # 생성 시 1회 스탬프(스펙 112)
    await _slugify_remote_agent(session, agent)  # 카드명은 원격 유래 — 자동 변환(스펙 148)
    session.add(agent)
    await _commit_or_409(session, "같은 식별 이름의 에이전트가 이미 있습니다.")
    return await _reload_out(session, agent.id)


# ----------------------------- 외부 에이전트 등록 (A2A 카드) — deprecated, connect로 대체 -----------------------------
@router.post("/external", response_model=AgentOut, status_code=201)
async def register_external_agent(
    body: RegisterExternalAgentIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    """A2A Agent Card URL을 fetch·검증해 외부 에이전트로 등록(026, 1차).

    057 이후 deprecated — 프론트는 connect를 호출한다. 라우트·로직은 무회귀 위해 잔존(connect의
    external 분기와 동일 빌더 공유). 실제 A2A 호출은 _a2a_stream.
    """
    try:
        card = await agent_card.fetch_card(body.cardUrl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    live = await agent_card.probe_endpoint(card.get("url"))
    agent = _build_external_agent(card, body.token, live, body.cardUrl)
    agent.owner_id = owner_of(principal)  # 생성 시 1회 스탬프(스펙 112)
    await _slugify_remote_agent(session, agent)  # 카드명은 원격 유래 — 자동 변환(스펙 148)
    session.add(agent)
    await _commit_or_409(session, "같은 식별 이름의 에이전트가 이미 있습니다.")
    return await _reload_out(session, agent.id)


async def _resync_display_only(
    session: AsyncSession, agent: Agent, *, offline: bool = False
) -> AgentOut:
    """카드 재해석 없이 표시(last_sync·선택적 offline)만 갱신하고 직렬화 응답을 반환."""
    if offline:
        agent.status = "offline"
    agent.last_sync = "방금"
    await session.commit()
    return await _reload_out(session, agent.id)


def _transition_active_commit(agent: Agent, new_commit: str, cfg: dict) -> None:
    """commit 변경 시 버전 행을 057 F4 불변식대로 전이(active_version은 항상 실재 active 행)."""
    agent.commit = new_commit
    existing = _find_version(agent, new_commit)
    for version in agent.versions:
        if version.status == "active":
            version.status = "archived"
    if existing is not None:
        existing.status = "active"  # A→B→A 재왕복: 기존 행 승격(중복 행 금지)
    else:
        agent.versions.append(
            AgentVersion(
                version=new_commit,
                status="active",
                note="resync 재보고(스펙 285)",
                config=dict(cfg),
            )
        )
    agent.active_version = new_commit


def _resync_deploy_meta(agent: Agent, card: dict, cfg: dict) -> None:
    """배포 메타 재보고(스펙 285) — 상태는 실측인데 버전(commit)은 등록 시점 신고라 낡던 비대칭 해소.

    code(확장 보유)만: repo·runtime은 값 있을 때만 갱신(카드에서 사라지면 기존 보존 — merge-preserve),
    commit 변경 시 버전 행을 057 F4 불변식대로 전이."""
    ext = agent_card.extract_my_agents(card)
    if agent.source != "code" or ext is None:
        return
    deploy = ext.get("deploy") or {}
    new_repo = _clip(deploy.get("repo"), 200)
    new_runtime = _clip(deploy.get("runtime"), 200)
    if new_repo:
        agent.repo = new_repo
    if new_runtime:
        agent.runtime = new_runtime
    new_commit = _clip(deploy.get("commit"), 80)  # 길이 하드닝(057 F3 동일)
    if new_commit and new_commit != agent.commit:
        _transition_active_commit(agent, new_commit, cfg)


# ----------------------------- 코드 에이전트 재동기화 -----------------------------
@router.post("/{agent_id}/resync", response_model=AgentOut)
async def resync_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> AgentOut:
    """stale endpoint 자가치유(스펙 081 P1).

    저장해둔 카드 출처(config["cardUrl"])에서 카드를 재fetch → `fetch_card`가 071의 prefix-상대
    endpoint resolution을 재실행 → endpoint·카드 스냅샷·status(probe liveness)를 in-place 갱신한다.
    071 보정은 fetch_card 시점에만 걸리므로, 071 이전 등록분·원격 변경분의 stale endpoint는 이 경로로만
    재연결 없이 고쳐진다. 기존 행 갱신이라 id/소유/버전은 보존(connect의 새 Agent 생성과 다름).

    cardUrl이 없는 레거시 행은 재해석 출처가 없어 last_sync만 갱신(재연결 1회 필요).
    SSRF 경계: fetch_card·probe_endpoint가 각각 저장된 cardUrl(connect 때 guard 통과한 사용자 입력)에서만
    guard_url 선행 — request Host 등 외부 파생 입력을 쓰지 않으므로 host-poisoning 무관(learning 064).
    """
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)

    cfg = dict(agent.config or {})
    card_url = cfg.get("cardUrl")
    if not isinstance(card_url, str) or not card_url:
        # 레거시(cardUrl 미저장): 재해석 출처 없음 → 기존 동작 유지(표시만 갱신). 한 번 재연결하면
        # 이후 connect가 cardUrl을 채워 자가치유 경로로 들어온다.
        return await _resync_display_only(session, agent)

    try:
        card = await agent_card.fetch_card(card_url)
    except ValueError:
        # 카드 출처 도달 실패 — 등록은 유지하되 status는 정직하게 offline(045 #2). endpoint는 보존
        # (다음 resync에서 재시도). 표시 갱신만.
        return await _resync_display_only(session, agent, offline=True)

    live = await agent_card.probe_endpoint(card.get("url"))
    cfg["card"] = card  # 카드 스냅샷 갱신(표시·검증 단일 소스)
    agent.config = cfg  # JSONB는 in-place 변이 미추적 — 재할당으로 더티 표기
    agent.endpoint = _norm_endpoint(card.get("url"))
    agent.status = "online" if live else "offline"
    agent.last_sync = "방금"
    _resync_deploy_meta(agent, card, cfg)
    await session.commit()
    return await _reload_out(session, agent.id)
