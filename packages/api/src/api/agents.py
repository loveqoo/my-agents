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
    ConnectAgentIn,
    ExposeIn,
    MemoryHit,
    MemorySearchIn,
    MemorySearchOut,
    RegisterCodeAgentIn,
    RegisterExternalAgentIn,
)
from . import agent_card, crypto, net_guard
from .serializers import agent_to_out

router = APIRouter(prefix="/agents", tags=["agents"])

# 능력 브로커 UI(스펙 106)용 메타 라우터 — `/agents/{id}`(uuid) 경로와 충돌 않게 top-level에 둔다.
meta_router = APIRouter(tags=["agents"])


@meta_router.get("/agent-impls", response_model=list[str])
async def list_impls() -> list[str]:
    """등록된 실행 방식(impl) 키 목록 — 신뢰 레지스트리 단일 출처(drift 0). 편집 폼 impl Select가 소비.
    키일 뿐(런타임 eval 없음, 스펙 085). agent.runtime import가 `_bootstrap_builtins()`를 이미 실행."""
    from agent.runtime import list_agent_impls

    return list_agent_impls()


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
    # impl(스펙 085 SDK 런타임 키)은 편집 폼이 아직 안 보내므로(SPA 미배선), 요청에 명시되지
    # 않으면 기존 값을 보존한다 — 안 그러면 Pydantic 기본 None이 덮어써 편집→활성화가 커스텀
    # 에이전트를 DefaultUiAgent로 silent 되돌린다(codex 적대 리뷰 F1). 편집 베이스(초안 있으면
    # 초안, 없으면 활성 config)의 impl을 이어받는다. 명시적으로 보내면(클리어 포함) 그 값 존중.
    if "impl" not in body.config.model_fields_set:
        base = (draft.config if draft is not None else None) or dict(agent.config or {})
        cfg["impl"] = base.get("impl")
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

    if body.a2a and agent.source != "ui":
        # 원격(code)·외부(external)는 이미 원격 A2A/프록시 — 우리 A2A로 재노출은 proxy-of-proxy(스펙 083).
        # A2A 서버(a2a_server._load_exposed_ui_agent)도 non-ui면 404라 노출해도 dead state. 입구에서 거부.
        # 단 a2a=False(끄기)는 source 무관 항상 허용 — stale 플래그를 멱등으로 청소하는 경로를 막지 않는다.
        raise HTTPException(
            status_code=400,
            detail="원격/외부 에이전트는 A2A로 노출할 수 없습니다 (source=ui만 노출 가능)",
        )
    # exposed는 JSONB(MutableDict 미추적) — 통째 교체 대신 형제 키 보존하며 a2a만 갱신 후 재대입.
    agent.exposed = {**(agent.exposed or {}), "a2a": body.a2a}
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 코드 에이전트 등록 -----------------------------
@router.post("/register", response_model=AgentOut, status_code=201)
async def register_code_agent(
    body: RegisterCodeAgentIn, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    # endpoint를 절대 http(s)로 정규화(스펙 060, 일관성). SDK 직접 등록이라 base는 없다 — 스킴 없는
    # host:port는 http:// 전치, 절대화 불가(빈 값·비-http 스킴)면 등록 시점에 400(채팅서 늦게 안 깸).
    try:
        endpoint = net_guard.normalize_http_url(body.endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
        endpoint=endpoint,
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


# ----------------------------- A2A 카드 → Agent 빌더 (connect/external 공유) -----------------------------
def _clip(value: object, maxlen: int) -> str | None:
    """카드/매니페스트 문자열을 DB 컬럼 상한에 맞춰 안전화(적대리뷰 057 Finding 3).

    제3자가 거대/잡 문자열을 흘려도 Postgres bounded 컬럼(String(N))에서 commit이 500나지 않게,
    문자열이 아니면 None, 너무 길면 잘라 반환한다(표시·provenance 메타라 절단 허용)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:maxlen]


def _norm_endpoint(raw: object) -> str | None:
    """카드 서비스 url을 절대 http(s)로 정규화해 저장(스펙 063, 빌더 하드닝).

    `fetch_card`가 이미 정규화하므로 정상 경로는 idempotent. fetch_card를 우회하는 미래 경로가
    스킴 없는 url을 흘려도 저장 데이터가 청결하게 유지된다(표시·probe도 같은 endpoint를 읽는다).
    정규화 불가(빈 값·비-http 스킴)면 clip한 raw를 그대로 보존 — 등록을 500내지 않고, 호출 경계
    (a2a_client, 스펙 063 D1)가 2차로 다시 시도한다."""
    clipped = _clip(raw, 400)
    if not clipped:
        return None
    try:
        return net_guard.normalize_http_url(clipped)
    except ValueError:
        return clipped


def _build_external_agent(card: dict, token: str | None, live: bool, card_url: str | None = None) -> Agent:
    """제3자 A2A 카드 → external Agent. 불투명 카드 스냅샷, 로컬 모델/메모리/MCP 미해석(비로컬).

    카드 스냅샷은 config["card"], 서비스 URL은 endpoint, 호출 크레덴셜은 crypto.encrypt로 token에
    저장(2차 런타임 호출에서 복호 사용).

    card_url = 카드를 가져온 출처(.well-known 위치). resync 자가치유(스펙 081)가 이 URL로 카드를
    재fetch해 endpoint·status를 갱신한다 — 저장 안 하면 stale endpoint를 재연결 없이 못 고친다."""
    cfg = {
        "model": "",  # 외부는 로컬 모델 미해석
        "persona": "",
        "memories": [],
        "vectorTables": [],
        "permissions": [],
        "mcps": [],
        "historyDepth": 10,
        "card": card,  # 등록 시점 카드 스냅샷(표시·검증 단일 소스)
        "cardUrl": card_url,  # 카드 출처 — resync 재해석용(스펙 081)
    }
    return Agent(
        agent_id=_new_agent_id(),
        name=_clip(card.get("name"), 200) or "외부 에이전트",
        source="external",
        model="",
        persona="",
        history_depth=10,
        config=cfg,
        exposed={"a2a": False},  # 우리가 소비측(클라이언트) — 서버측 노출과 무관
        status="online" if live else "offline",
        endpoint=_norm_endpoint(card.get("url")),
        token=crypto.encrypt(token) if token else None,
        registered_at=_today(),
        last_sync="방금",
    )


def _build_code_agent_from_card(card: dict, ext: dict, token: str | None, live: bool, card_url: str | None = None) -> Agent:
    """제1자(SDK 배포) A2A 카드 + my-agents 확장 → code Agent (스펙 057).

    config는 ext["manifest"](model/persona/mcps/…)에서 채우고 카드 스냅샷을 함께 보존한다.
    repo/commit/runtime·AgentVersion은 ext["deploy"]에서 만든다. **전부 카드에서 fetch — 프론트
    날조 없음**. A2A 호출엔 카드 url+token만 쓰지만(현 external과 동일), 저장 config는 1급 표시·resync용.
    """
    manifest = ext["manifest"]
    deploy = ext["deploy"]
    history_depth = manifest.get("historyDepth")
    if not isinstance(history_depth, int):
        history_depth = 10
    cfg = {
        "model": manifest.get("model") or "",
        "persona": manifest.get("persona") or "",
        "memories": manifest.get("memories") if isinstance(manifest.get("memories"), list) else [],
        "vectorTables": [],
        "permissions": manifest.get("permissions") if isinstance(manifest.get("permissions"), list) else [],
        "mcps": manifest.get("mcps") if isinstance(manifest.get("mcps"), list) else [],
        "historyDepth": history_depth,
        "card": card,  # 카드 스냅샷 — external과 동일하게 표시·검증 단일 소스
        "cardUrl": card_url,  # 카드 출처 — resync 재해석용(스펙 081)
    }
    # 길이 하드닝(적대리뷰 057 Finding 3) — bounded 컬럼에 잡/거대 문자열이 들어가 commit이 500나지 않게.
    commit = _clip(deploy.get("commit"), 80)
    agent = Agent(
        agent_id=_new_agent_id(),
        name=_clip(card.get("name"), 200) or _clip(deploy.get("repo"), 200) or "SDK 에이전트",
        source="code",
        model=_clip(cfg["model"], 120) or "",
        persona=cfg["persona"],  # Text 컬럼 — 무제한
        history_depth=history_depth,
        config=cfg,
        exposed={"a2a": False},
        status="online" if live else "offline",
        endpoint=_norm_endpoint(card.get("url")),
        token=crypto.encrypt(token) if token else None,
        runtime=_clip(deploy.get("runtime"), 200),
        repo=_clip(deploy.get("repo"), 200),
        commit=commit,
        registered_at=_today(),
        last_sync="방금",
    )
    # 버전 빌드 + active_version 불변식(적대리뷰 057 Finding 4): active_version은 항상 실재하는 active
    # AgentVersion을 가리키거나 None. deploy.versions 잡값(빈 리스트·archived만·잡 버전)이 와도 active
    # row 없이 active_version만 세팅되는 불일치를 만들지 않는다.
    active_version_id: str | None = None
    raw_versions = deploy.get("versions")
    if isinstance(raw_versions, list):
        for v in raw_versions:
            if not isinstance(v, dict):
                continue
            vid = _clip(v.get("version"), 40)
            if vid is None:
                continue
            vstatus = _clip(v.get("status"), 20) or "archived"
            if vstatus == "active" and active_version_id is None:
                active_version_id = vid
            agent.versions.append(
                AgentVersion(
                    version=vid,
                    status=vstatus,
                    note=v.get("note") if isinstance(v.get("note"), str) else "",
                    config=cfg,
                )
            )
    if active_version_id is None and commit:
        # 카드에 active 버전이 없으면 commit으로 active 1개 합성(external register와 일관). 합성한 뒤에만
        # active_version을 세팅 — 실재하는 row를 보장한다.
        synth = _clip(commit, 40)
        agent.versions.append(
            AgentVersion(version=synth, status="active", note="Deploy · 카드 동기화", config=cfg)
        )
        active_version_id = synth
    agent.active_version = active_version_id
    return agent


# ----------------------------- 통합 연결 (스펙 057 — A2A 단일화) -----------------------------
@router.post("/connect", response_model=AgentOut, status_code=201)
async def connect_agent(
    body: ConnectAgentIn, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    """원격 에이전트 연결 — URL 하나로 A2A 카드를 fetch해 provenance 자동분류(스펙 057).

    카드에 my-agents 확장(x-my-agents.manifest)이 있으면 우리가 SDK로 배포한 제1자(source=code,
    매니페스트·배포 메타 보유), 없으면 제3자 A2A(source=external, 불투명). 둘 다 런타임은 A2A 하나.
    SSRF 가드는 fetch_card·probe_endpoint가 각각 guard_url 선행(044/055).
    """
    try:
        card = await agent_card.fetch_card(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 카드 published ≠ 실행 엔드포인트 live(045 #2). 도달 실패해도 등록 허용, status만 정직하게.
    live = await agent_card.probe_endpoint(card.get("url"))
    ext = agent_card.extract_my_agents(card)
    if ext is not None:
        agent = _build_code_agent_from_card(card, ext, body.token, live, body.url)
    else:
        agent = _build_external_agent(card, body.token, live, body.url)
    session.add(agent)
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 외부 에이전트 등록 (A2A 카드) — deprecated, connect로 대체 -----------------------------
@router.post("/external", response_model=AgentOut, status_code=201)
async def register_external_agent(
    body: RegisterExternalAgentIn, session: AsyncSession = Depends(get_session)
) -> AgentOut:
    """A2A Agent Card URL을 fetch·검증해 외부 에이전트로 등록(026, 1차).

    057 이후 deprecated — 프론트는 connect를 호출한다. 라우트·로직은 무회귀 위해 잔존(connect의
    external 분기와 동일 빌더 공유). 실제 A2A 호출은 _a2a_stream.
    """
    try:
        card = await agent_card.fetch_card(body.cardUrl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    live = await agent_card.probe_endpoint(card.get("url"))
    agent = _build_external_agent(card, body.token, live, body.cardUrl)
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


@router.post("/{agent_id}/memory/search", response_model=MemorySearchOut)
async def search_agent_memory(
    agent_id: uuid.UUID, body: MemorySearchIn, session: AsyncSession = Depends(get_session)
) -> MemorySearchOut:
    """회상 시험(스펙 084) — 챗과 동일한 공유 코어 `memory.search`로 agent_id 스코프 회상.

    에이전트 메모리는 유저 축이 아니라 기존 agent-memory CRUD처럼 router-auth만(새 principal 게이트
    없음). 스코프 dict가 mem0 filter로 들어가 이 에이전트 기억만 로드. 미구성이면 enabled=False·빈결과."""
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)
    # recall_probe: 백엔드 미가용(mem_cfg None·구성 실패)이면 None → enabled=False. 가용이면
    # limit로 슬라이스된 리스트. enabled를 mem_cfg 유무가 아닌 *백엔드 가용성*에 묶어 깨진
    # 백엔드를 "회상 0건"으로 위장하지 않는다(적대 리뷰 084 P2a·P2b).
    hits = await asyncio.to_thread(
        memory.recall_probe, {"agent_id": agent.agent_id}, body.query, mem_cfg, body.limit
    )
    return MemorySearchOut(
        query=body.query,
        limit=body.limit,
        enabled=hits is not None,
        results=[MemoryHit(**h) for h in (hits or [])],
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

    cfg = dict(agent.config or {})
    card_url = cfg.get("cardUrl")
    if not isinstance(card_url, str) or not card_url:
        # 레거시(cardUrl 미저장): 재해석 출처 없음 → 기존 동작 유지(표시만 갱신). 한 번 재연결하면
        # 이후 connect가 cardUrl을 채워 자가치유 경로로 들어온다.
        agent.last_sync = "방금"
        await session.commit()
        return await _reload_out(session, agent.id)

    try:
        card = await agent_card.fetch_card(card_url)
    except ValueError:
        # 카드 출처 도달 실패 — 등록은 유지하되 status는 정직하게 offline(045 #2). endpoint는 보존
        # (다음 resync에서 재시도). 표시 갱신만.
        agent.status = "offline"
        agent.last_sync = "방금"
        await session.commit()
        return await _reload_out(session, agent.id)

    live = await agent_card.probe_endpoint(card.get("url"))
    cfg["card"] = card  # 카드 스냅샷 갱신(표시·검증 단일 소스)
    agent.config = cfg  # JSONB는 in-place 변이 미추적 — 재할당으로 더티 표기
    agent.endpoint = _norm_endpoint(card.get("url"))
    agent.status = "online" if live else "offline"
    agent.last_sync = "방금"
    await session.commit()
    return await _reload_out(session, agent.id)
