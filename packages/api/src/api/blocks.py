"""빌딩 블록 카탈로그 CRUD + 관리자 UI 집계 (REST).

페르소나·메모리타입·MCP 서버의 전체 CRUD와, 관리자 콘솔이 한 번에 읽는 4개
카테고리 집계(`GET /blocks`)를 제공한다. embedding 카테고리는 RAG 컬렉션(스펙 036)을
읽기 전용으로 비춘다 — 컬렉션 CRUD/인제스트는 `rag.py`(`/collections`)가 담당한다.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto
from .auth import current_principal
from .db import get_session
from .naming import validate_resource_name
from .ownership import assert_may_manage, may_manage, may_use_agent, owner_of
from agent.runtime import is_first_party
from .models import Agent, Collection, McpServer, MemoryType, Persona
from .references import _config_has, agents_referencing, referenced_message
from .schemas import (
    McpDiscoverIn,
    McpDiscoverResult,
    McpPublishIn,
    McpServerIn,
    McpServerOut,
    MemoryTypeIn,
    MemoryTypeOut,
    PersonaApplyIn,
    PersonaApplyOut,
    PersonaIn,
    PersonaOut,
    PersonaUsageAgentOut,
)

router = APIRouter(tags=["blocks"])


def _assert_valid_name(name: str) -> None:
    """식별 이름 규칙(스펙 148) — 위반이면 400. 생성·이름 변경 시에만(기존은 grandfather)."""
    err = validate_resource_name(name)
    if err:
        raise HTTPException(status_code=400, detail=err)


def _norm_description(data: dict) -> dict:
    """설명 정규화 — 공백뿐이면 None(스펙 148, 210)."""
    if "description" in data:
        data["description"] = (data["description"] or "").strip() or None
    return data


async def _commit_or_409(session: AsyncSession, detail: str) -> None:
    """이름 유니크 충돌을 500 대신 409로(스펙 148 — name unique 테이블 공용)."""
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail)


# ----------------------------- 페르소나 -----------------------------
@router.get("/personas", response_model=list[PersonaOut])
async def list_personas(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(Persona))
    return result.scalars().all()


@router.post("/personas", response_model=PersonaOut, status_code=201)
async def create_persona(body: PersonaIn, session: AsyncSession = Depends(get_session)) -> Any:
    _assert_valid_name(body.name)  # 식별 이름 규칙(스펙 148)
    obj = Persona(**_norm_description(body.model_dump()))
    session.add(obj)
    await _commit_or_409(session, "같은 식별 이름의 페르소나가 이미 있습니다.")
    await session.refresh(obj)
    return obj


@router.get("/personas/{id}", response_model=PersonaOut)
async def get_persona(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.put("/personas/{id}", response_model=PersonaOut)
async def update_persona(
    id: uuid.UUID, body: PersonaIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    if body.name != obj.name:
        _assert_valid_name(body.name)  # 이름 변경 시에만 규칙(기존은 grandfather, 스펙 148)
        # rename도 config["persona"] 참조를 깬다 — MCP(093)와 동일 가드(codex 148 High)
        refs = await agents_referencing(session, "persona", obj.name)
        if refs:
            raise HTTPException(status_code=409, detail=referenced_message(refs, "페르소나", action="이름 변경"))
    for key, value in _norm_description(body.model_dump()).items():
        setattr(obj, key, value)
    await _commit_or_409(session, "같은 식별 이름의 페르소나가 이미 있습니다.")
    await session.refresh(obj)
    return obj


@router.get("/personas/{id}/agents", response_model=list[PersonaUsageAgentOut])
async def persona_agents(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> Any:
    """이 페르소나를 쓰는 에이전트 + 각 오래됨(stale) 상태(스펙 161). 편집 화면이 "N개 사용·M개
    오래됨"과 선택 반영 대상을 그린다. stale = 에이전트 스냅샷(agent.persona) != 현재 본문(obj.body)."""
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    agents = (await session.execute(select(Agent))).scalars().all()
    return [
        PersonaUsageAgentOut(
            id=a.id, agentId=a.agent_id, name=a.name, description=a.description,
            stale=(a.persona != obj.body),
            canManage=may_manage(a.owner_id, principal),
        )
        for a in agents
        # may_use_agent 가시성 필터(스펙 147, codex 161 High) — 타인 private 에이전트의 식별자·stale를
        # 누출하지 않는다(일반 list/get/chat과 동일 게이트). admin/machine은 전부, member는 본인+public.
        if is_first_party(a.source)
        and may_use_agent(a, principal)
        and _config_has(a.config, "persona", obj.name)
    ]


@router.post("/personas/{id}/apply", response_model=PersonaApplyOut)
async def persona_apply(
    id: uuid.UUID,
    body: PersonaApplyIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> Any:
    """선택 에이전트들의 페르소나 스냅샷을 이 페르소나 최신 본문으로 반영(스펙 161). **각 에이전트
    can_manage 게이트** — 관리 불가/이 페르소나 미참조 대상은 건너뛴다(남의 에이전트 무단 변경 금지)."""
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    want = set(body.agentIds)
    agents = (await session.execute(select(Agent).where(Agent.id.in_(want)))).scalars().all()
    applied: list[uuid.UUID] = []
    skipped: list[uuid.UUID] = []
    found = {a.id for a in agents}
    for a in agents:
        # 이 페르소나를 실제 참조하고(활성 config) 관리 권한이 있어야 반영. 아니면 skip.
        if (
            is_first_party(a.source)
            and _config_has(a.config, "persona", obj.name)
            and may_manage(a.owner_id, principal)
        ):
            a.persona = obj.body  # 스냅샷 = 현재 본문(in-place, 이름 불변이라 새 버전 없음)
            applied.append(a.id)
        else:
            skipped.append(a.id)
    skipped.extend(aid for aid in want if aid not in found)  # 미존재도 skip으로 정직 보고
    if applied:
        await session.commit()
    return PersonaApplyOut(applied=applied, skipped=skipped)


@router.delete("/personas/{id}", status_code=204)
async def delete_persona(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    # 참조 중 삭제 차단(093 operation-symmetry를 페르소나에도 — codex 148 High): 지우면
    # resolve_persona가 name 문자열 자체를 시스템 프롬프트로 쓰는 조용한 degrade가 생긴다.
    refs = await agents_referencing(session, "persona", obj.name)
    if refs:
        raise HTTPException(status_code=409, detail=referenced_message(refs, "페르소나"))
    await session.delete(obj)
    await session.commit()


# ----------------------------- 메모리 타입 -----------------------------
@router.get("/memory-types", response_model=list[MemoryTypeOut])
async def list_memory_types(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(MemoryType))
    return result.scalars().all()


@router.post("/memory-types", response_model=MemoryTypeOut, status_code=201)
async def create_memory_type(
    body: MemoryTypeIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = MemoryType(**body.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/memory-types/{id}", response_model=MemoryTypeOut)
async def get_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(MemoryType, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.put("/memory-types/{id}", response_model=MemoryTypeOut)
async def update_memory_type(
    id: uuid.UUID, body: MemoryTypeIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(MemoryType, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    for key, value in body.model_dump().items():
        setattr(obj, key, value)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.delete("/memory-types/{id}", status_code=204)
async def delete_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await session.get(MemoryType, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(obj)
    await session.commit()


# 벡터 테이블 CRUD는 RAG 컬렉션(스펙 036)으로 대체 — rag.py(`/collections`)가 담당.
# embedding 카테고리 집계는 get_blocks에서 Collection을 읽기 전용으로 비춘다.


# ----------------------------- 권한 -----------------------------


# ----------------------------- MCP 서버 -----------------------------
# 도구 메타 캡(스펙 151) — 원격 유래 문자열이라 표시·저장 상한을 입력 경계에서 건다.
_TOOL_DESC_CAP = 500
_TOOL_PARAMS_CAP = 30
_TOOLS_META_CAP = 100  # 서버당 메타 저장 도구 수 상한


def _tool_info(t) -> dict:
    """langchain 도구 객체 → {name, description, params[{name,type,required}]} (스펙 151).
    스키마 파생 실패는 params=[]로 접는다(표시용 — 탐색 자체를 죽이지 않는다). 순수 함수."""
    params: list[dict] = []
    try:
        props = dict(getattr(t, "args", None) or {})
        required: set[str] = set()
        try:
            schema = t.tool_call_schema
            js = schema.model_json_schema() if hasattr(schema, "model_json_schema") else (schema or {})
            required = set(js.get("required") or [])
        except Exception:  # noqa: BLE001 — required 미상은 False로
            pass
        for pname, ps in list(props.items())[:_TOOL_PARAMS_CAP]:
            ptype = "any"
            if isinstance(ps, dict):
                if isinstance(ps.get("type"), str):
                    ptype = ps["type"]
                elif isinstance(ps.get("anyOf"), list):
                    ptype = "/".join(
                        str(x.get("type", "?")) for x in ps["anyOf"] if isinstance(x, dict)
                    ) or "any"
            params.append({"name": str(pname)[:80], "type": str(ptype)[:40], "required": pname in required})
    except Exception:  # noqa: BLE001
        params = []
    return {
        "name": str(getattr(t, "name", ""))[:120],
        "description": str(getattr(t, "description", "") or "")[:_TOOL_DESC_CAP],
        "params": params,
    }


def _tools_meta_from_details(details: list[dict], prior: dict | None = None) -> dict:
    """toolsDetail 리스트 → 저장용 dict(name→{description, params[, approval]}). 서버당 상한 적용.

    approval(도구 승인 정책, 스펙 177)은 **라이브 탐색이 보고하지 않는 관리자 데이터**다. 재탐색 시
    이 함수가 tools_meta를 통째 교체하므로, `prior`(기존 tools_meta)에서 도구별 approval을 **이월
    보존**하지 않으면 재탐색 한 번에 관리자가 켠 승인 게이트가 소멸한다(적대 검토 P0 — 단위는 초록,
    reconcile 왕복만 잡는 결함). 도구명이 재탐색으로 사라지면 그 approval도 함께 사라진다(정상)."""
    prior = prior or {}
    out: dict = {}
    for d in details[:_TOOLS_META_CAP]:
        name = d.get("name")
        if not name:
            continue
        entry = {"description": d.get("description", ""), "params": d.get("params", [])}
        prev = prior.get(name)
        pa = prev.get("approval") if isinstance(prev, dict) else None
        if isinstance(pa, dict) and pa.get("required"):
            entry["approval"] = {"required": True}  # 관리자 정책 이월(탐색 결과엔 없음)
        out[name] = entry
    return out


def _mcp_auth_masked(obj: McpServer) -> str | None:
    """저장된 auth(암호문)를 응답용 마스킹값으로 — 평문/암호문 절대 미노출(스펙 054 F, 누출-안전)."""
    return crypto.SECRET_MASK if obj.auth else None


def _mcp_served_url(obj: McpServer) -> str | None:
    """서빙 URL(스펙 156) — source=custom이고 레지스트리에 실 정의가 있는 이름만. 그 외 None
    (등록만 있고 서빙 정의 없는 custom 이름은 URL을 광고하지 않는다). base는 A2A_SELF_BASE_URL 재사용."""
    from . import served_mcp

    if obj.source != served_mcp.SERVABLE_SOURCE or obj.name not in served_mcp.SERVED_MCPS:
        return None
    import os

    base = (os.environ.get("A2A_SELF_BASE_URL") or "http://127.0.0.1:8000").strip()
    return served_mcp.served_url(obj.name, base)


def mcp_to_out(obj: McpServer) -> McpServerOut:
    """ORM → 응답 DTO. auth는 마스킹해 평문 토큰을 절대 흘리지 않는다."""
    return McpServerOut(
        served_url=_mcp_served_url(obj),
        id=obj.id,
        name=obj.name,
        description=obj.description,  # 설명(스펙 210)
        source=obj.source,
        transport=obj.transport,
        url=obj.url,
        endpoint=obj.endpoint,
        tools=list(obj.tools or []),
        enabled_tools=list(obj.enabled_tools or []),
        tools_meta=obj.tools_meta,  # 도구 메타(스펙 151)
        status=obj.status,
        published=obj.published,
        auth=_mcp_auth_masked(obj),
        owner_id=obj.owner_id,  # 스펙 112(can_manage는 list서 세팅)
    )


@router.get("/mcp-servers", response_model=list[McpServerOut])
async def list_mcp_servers(
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> Any:
    result = await session.execute(select(McpServer))
    outs = [mcp_to_out(o) for o in result.scalars().all()]
    for o in outs:  # 스펙 114 — 관리 가능 여부 파생
        o.can_manage = may_manage(o.owner_id, principal)
    return outs


@router.post("/mcp-servers", response_model=McpServerOut, status_code=201)
async def create_mcp_server(
    body: McpServerIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> Any:
    _assert_valid_name(body.name)  # 식별 이름 규칙(스펙 148) — 서버 등록명은 사용자가 짓는다
    from . import served_mcp

    if body.name in served_mcp.SERVED_MCPS:
        # 서빙 예약 이름(스펙 156) — 사용자가 서빙 레지스트리 이름(calc-tools 등)을 어떤 source로도
        # 선점하지 못하게 한다(선점 시 시스템 reconcile이 그 이름을 못 만들어 서빙이 막히는 스쿼팅 차단).
        raise HTTPException(status_code=400, detail="예약된 서빙 MCP 이름입니다 — 다른 이름을 쓰세요.")
    if body.source == "custom":
        # 커스텀(내부 코드 정의) MCP는 **시스템 전용**(스펙 156, codex High) — provenance를 자가선언해
        # 내부 레지스트리 이름(calc-tools 등)을 선점·공개하는 우회를 봉인한다. custom 행은 오직 seed의
        # 멱등 reconcile만 만든다(owner_id=None). 사용자는 local/external만 등록. (152 유래-불변 계열)
        raise HTTPException(status_code=400, detail="커스텀(내부 정의) MCP는 시스템 전용입니다 — 사용자가 생성할 수 없습니다.")
    if body.published and body.source != "custom":
        # published=커스텀 외부 서빙 전용(스펙 211, 152 재공개 금지 포함). 사용자는 custom 생성이
        # 불가하므로(위 게이트) 사실상 생성 경로에서 published=true는 항상 400.
        raise HTTPException(status_code=400, detail="외부 서빙은 커스텀 MCP만 켤 수 있습니다.")
    data = _norm_description(body.model_dump())
    data["enabled_tools"] = body.enabled_tools or body.tools
    # auth는 평문 입력 → Fernet 암호화 저장. 마스킹값이 들어오면(신규엔 없어야 함) 비워둔다.
    data["auth"] = None if (body.auth and crypto.is_masked(body.auth)) else crypto.encrypt(body.auth)
    data["owner_id"] = owner_of(principal)  # 생성 시 1회 스탬프(스펙 112)
    obj = McpServer(**data)
    session.add(obj)
    await _commit_or_409(session, "같은 식별 이름의 MCP 서버가 이미 있습니다.")
    await session.refresh(obj)
    return mcp_to_out(obj)


async def _live_discover(url: str, token: str | None) -> McpDiscoverResult:
    """MCP 라이브 탐색 공유 코어(스펙 054 E·151) — SSRF guard → 연결 → 이름+메타.
    discover(폼, 평문/마스킹 토큰)와 rediscover(저장 서버, 복호 토큰)가 공유(드리프트 0).
    SsrfBlocked는 HTTPException 400으로 올린다(보안 경계 ≠ 정상 연결실패)."""
    import asyncio
    import time

    from langchain_mcp_adapters.client import MultiServerMCPClient

    from . import net_guard

    try:
        await net_guard.refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064)
        net_guard.guard_url(url)
    except net_guard.SsrfBlocked as exc:
        # 보안 경계 위반은 4xx(정상 연결실패의 ok=False와 구분) — 스펙 054 완료조건 ④.
        raise HTTPException(status_code=400, detail=str(exc)) from None

    headers = {"Authorization": f"Bearer {token}"} if token else None
    t0 = time.perf_counter()
    try:
        client = MultiServerMCPClient(
            {"probe": {
                "transport": "streamable_http", "url": url, "headers": headers,
                # 리다이렉트-SSRF 차단(적대 리뷰 H1) — runtime.build_mcp_tools와 동일 정책.
                "httpx_client_factory": net_guard.mcp_http_client_factory,
            }}
        )
        async with asyncio.timeout(15):
            tools = await client.get_tools(server_name="probe")
    except Exception:  # noqa: BLE001 — 연결/프로토콜 오류(상세 미노출, 비밀 에코 방지)
        ms = int((time.perf_counter() - t0) * 1000)
        return McpDiscoverResult(ok=False, reachable=False, latencyMs=ms, detail="연결 실패")
    ms = int((time.perf_counter() - t0) * 1000)
    names = [t.name for t in tools]
    details = [_tool_info(t) for t in tools[:_TOOLS_META_CAP]]  # 메타(설명·파라미터, 스펙 151)
    return McpDiscoverResult(
        ok=True, reachable=True, tools=names, toolsDetail=details, latencyMs=ms,
        detail=f"{len(names)}개 도구 발견",
    )


@router.post("/mcp-servers/discover", response_model=McpDiscoverResult)
async def discover_mcp_tools(body: McpDiscoverIn) -> Any:
    """저장 전 폼에서 MCP 서버에 **실제로 붙어** 도구목록을 읽는다(부작용 0 — list만). 등록 자동채움용(스펙 054 E).

    stdio는 유예 — http만 라이브 탐색. 비밀은 결과에 미포함(latency·도구이름·메타만).
    마스킹(•) auth는 헤더 생략(a2a_client 규칙).
    """
    url = (body.url or "").strip()
    if body.transport != "http":
        return McpDiscoverResult(
            ok=False, reachable=False, detail="stdio transport는 라이브 탐색 미지원(유예)"
        )
    token = (body.auth or "").strip()
    return await _live_discover(url, token if token and "•" not in token else None)


@router.post("/mcp-servers/{id}/rediscover", response_model=McpServerOut)
async def rediscover_mcp_server(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> Any:
    """저장된 MCP 서버의 도구·메타를 재탐색해 갱신(스펙 151 — 상세 화면 '도구 정보 새로 탐색').

    저장된 자격증명을 **백엔드에서 복호**해 쓴다(프론트는 마스킹 토큰만 가져 재탐색 불가).
    enabled_tools는 새 목록과의 교집합으로 보존(사라진 도구만 떨어냄 — 임의 활성화 없음)."""
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(obj, principal)  # 소유자/특권만(스펙 112)
    if obj.transport != "http" or not obj.url:
        raise HTTPException(status_code=400, detail="http transport + URL이 있는 서버만 재탐색할 수 있습니다.")
    token = crypto.decrypt(obj.auth) if obj.auth else None
    r = await _live_discover(obj.url, token)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"재탐색 실패 — {r.detail}")
    # 참조 보호(codex 151 Medium): 원격이 일시적으로 도구를 빠뜨리면 재탐색 한 번에 에이전트의
    # 툴 단위 능력(`mcp:{서버}/{도구}`)이 조용히 사라진다 — 제거될 도구를 참조하는 에이전트가
    # 있으면 409(rename/삭제 가드와 같은 operation-symmetry).
    removed = [t for t in (obj.enabled_tools or []) if t not in set(r.tools)]
    if removed:
        agents = list((await session.execute(select(Agent))).scalars().all())
        refs = []
        for agent in agents:
            caps = (agent.config or {}).get("capabilities") if isinstance(agent.config, dict) else None
            if isinstance(caps, list) and any(f"mcp:{obj.name}/{t}" in caps for t in removed):
                refs.append({"agent": agent.name, "where": "active"})
        if refs:
            raise HTTPException(
                status_code=409,
                detail=referenced_message(refs, f"MCP 도구({', '.join(removed[:5])})", action="재탐색(도구 제거)"),
            )
    obj.tools = r.tools
    # 기존 tools_meta를 넘겨 관리자 승인 정책(approval, 스펙 177)을 이월 보존 — 재탐색이 게이트를 지우지 않게.
    obj.tools_meta = _tools_meta_from_details([d.model_dump() for d in r.toolsDetail], obj.tools_meta)
    obj.enabled_tools = [t for t in (obj.enabled_tools or []) if t in r.tools]
    obj.status = "connected"
    await session.commit()
    await session.refresh(obj)
    return mcp_to_out(obj)


@router.get("/mcp-servers/{id}", response_model=McpServerOut)
async def get_mcp_server(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return mcp_to_out(obj)


@router.put("/mcp-servers/{id}", response_model=McpServerOut)
async def update_mcp_server(
    id: uuid.UUID,
    body: McpServerIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(obj, principal)  # 소유자/특권만(스펙 112)
    data = _norm_description(body.model_dump())
    # source(유래)는 생성 후 불변(스펙 152, codex High) — external→local 세탁 후 publish하는
    # 재공개 우회를 봉인. provenance는 등록 시점의 사실이지 편집 대상이 아니다.
    if data.get("source") and data["source"] != obj.source:
        raise HTTPException(status_code=400, detail="source(유래)는 생성 후 변경할 수 없습니다.")
    # published=커스텀 외부 서빙 전용(스펙 211, 152 재공개 금지 포함) — 끄기는 항상 허용.
    if data.get("published") and obj.source != "custom":
        raise HTTPException(status_code=400, detail="외부 서빙은 커스텀 MCP만 켤 수 있습니다.")
    if data.get("tools_meta") is None:
        data.pop("tools_meta", None)  # None=미변경(스펙 151 — 편집 폼이 메타를 안 들고 있어도 보존)
    # 참조 무결성(스펙 093, operation-symmetry): rename도 삭제와 똑같이 config의 name 링크를 끊는다.
    # 런타임은 McpServer.name.in_(config["mcps"])로 해석하므로 참조 중인 서버 name을 바꾸면 옛 name이
    # dangling 되어 도구가 조용히 사라진다 → 참조가 있으면 rename을 409로 막는다(값은 옛 name 기준).
    new_name = data.get("name")
    if new_name is not None and new_name != obj.name:
        _assert_valid_name(new_name)  # 이름 변경 시에만 규칙(기존은 grandfather, 스펙 148)
        refs = await agents_referencing(session, "mcps", obj.name)
        if refs:
            raise HTTPException(
                status_code=409, detail=referenced_message(refs, "MCP 서버", action="이름 변경")
            )
    # auth 의미 구분(provider.api_key와 동형): None/마스킹 = 기존 암호화 토큰 보존,
    # 빈 문자열 = 명시적 제거, 그 외 = 새 평문 암호화. 마스킹값이 그대로 저장되는 버그 방지.
    auth_in = data.pop("auth", None)
    for key, value in data.items():
        setattr(obj, key, value)
    if auth_in is None or crypto.is_masked(auth_in):
        pass  # 보존
    elif auth_in == "":
        obj.auth = None
    else:
        obj.auth = crypto.encrypt(auth_in)
    await _commit_or_409(session, "같은 식별 이름의 MCP 서버가 이미 있습니다.")
    await session.refresh(obj)
    return mcp_to_out(obj)


@router.delete("/mcp-servers/{id}", status_code=204)
async def delete_mcp_server(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> None:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(obj, principal)  # 소유자/특권만(스펙 112)
    # 참조 무결성(스펙 093): 이 서버 name을 config에 담은 에이전트가 있으면 삭제 차단.
    # 삭제하면 config에 dangling name만 남아 런타임이 조용히 도구 없이 동작한다.
    refs = await agents_referencing(session, "mcps", obj.name)
    if refs:
        raise HTTPException(
            status_code=409, detail=referenced_message(refs, "MCP 서버")
        )
    await session.delete(obj)
    await session.commit()


@router.put("/mcp-servers/{id}/publish", response_model=McpServerOut)
async def publish_mcp_server(
    id: uuid.UUID,
    body: McpPublishIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(obj, principal)  # 소유자/특권만(스펙 112)
    if body.published and obj.source != "custom":
        # published=커스텀 MCP "외부 서빙" 전용 축(스펙 211 — 사용 공유 게이트 소멸로 의미 축소).
        # external 재공개 금지(스펙 152)를 포함해 non-custom은 켤 수 없다(서빙 레지스트리가 custom만
        # 서빙해 켜져도 무의미 — 무의미 상태를 만들지 않는다). UI는 스위치를 숨기지만 API 봉인이
        # 진실원(installed≠covering). 끄기는 항상 허용(stale 플래그 멱등 청소, 083 관례).
        raise HTTPException(status_code=400, detail="외부 서빙은 커스텀 MCP만 켤 수 있습니다.")
    obj.published = body.published
    await session.commit()
    await session.refresh(obj)
    return mcp_to_out(obj)


# ----------------------------- 집계 (관리자 UI) -----------------------------
_CATEGORY_META: dict[str, dict[str, str]] = {
    "persona": {
        "label": "페르소나",
        "icon": "smile",
        "color": "var(--magenta-6)",
        "desc": "에이전트가 따르는 성격·말투 정의(재사용 가능).",
    },
    "memory": {
        "label": "메모리 타입",
        "icon": "bulb",
        "color": "var(--purple-6)",
        "desc": (
            "에이전트가 컨텍스트를 저장·검색하는 메모리 타입. 서로 배타적이지 않으며, "
            "에이전트마다 여러 타입을 동시에 켤 수 있습니다."
        ),
    },
    "embedding": {
        "label": "RAG 컬렉션",
        "icon": "appstore",
        "color": "var(--cyan-7)",
        "desc": (
            "임베딩 모델 1개로 묶인 문서 컬렉션(RAG). 문서를 업로드하면 청킹·임베딩되어 "
            "pgvector에 적재되고, 에이전트가 의미 검색으로 참조합니다. 차원은 임베딩 모델에 "
            "맞춰 생성 시 고정됩니다. 에이전트마다 0개 이상 연결할 수 있습니다."
        ),
    },
    "mcp": {
        "label": "MCP 서버",
        "icon": "thunderbolt",
        "color": "var(--cyan-7)",
        "desc": (
            "Model Context Protocol 서버. 직접 운영하는 로컬 서버는 프로토콜로 공개할 수 있고, "
            "외부에서 공개된 MCP는 URL로 등록할 수 있습니다."
        ),
    },
}


def _count_by(agents: list[Agent], key: str, name: str, *, scalar: bool = False) -> int:
    """이름이 에이전트 *활성* config 배열(또는 스칼라 값)에 포함된 횟수(usedBy 배지용).

    배열 멤버십은 references._config_has로 위임(삭제 가드와 판정 로직 단일화, 드리프트 0).
    스펙 121 이후 삭제 가드(agents_referencing)도 **활성 config만** 세므로 배지와 답하는 질문이
    일치한다(과거 예엔 삭제만 버전까지 세던 어긋남을 121이 해소)."""
    total = 0
    for agent in agents:
        config = agent.config or {}
        if scalar:
            if config.get(key) == name:
                total += 1
        elif _config_has(config, key, name):
            total += 1
    return total


@router.get("/blocks")
async def get_blocks(
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> dict[str, Any]:
    agents = list((await session.execute(select(Agent))).scalars().all())

    personas = list((await session.execute(select(Persona))).scalars().all())
    memory_types = list((await session.execute(select(MemoryType))).scalars().all())
    collections = list(
        (
            await session.execute(
                select(Collection).options(selectinload(Collection.embedding_model))
            )
        ).scalars().all()
    )
    mcp_servers = list((await session.execute(select(McpServer))).scalars().all())

    persona_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,  # 설명(스펙 210)
            "tone": row.tone,
            "body": row.body,
            "usedBy": _count_by(agents, "persona", row.name, scalar=True),
            "updated": "—",
        }
        for row in personas
    ]
    memory_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "key": row.key,
            "scope": row.scope,
            "body": row.body,
            "usedBy": _count_by(agents, "memories", row.name),
            "updated": "—",
        }
        for row in memory_types
    ]
    embedding_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "kind": row.kind,  # document|entity(스펙 149)
            "model": row.embedding_model.name if row.embedding_model else "",
            "dims": row.dims,
            "docs": row.doc_count,
            "chunks": row.chunk_count,
            "chunkSize": row.chunk_size,
            "chunkOverlap": row.chunk_overlap,
            "status": row.status,
            "body": row.description,
            "usedBy": _count_by(agents, "vectorTables", row.name),
            "updated": "—",
        }
        for row in collections
    ]
    mcp_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,  # 설명(스펙 210)
            "source": row.source,
            "transport": row.transport,
            "url": row.url,
            "endpoint": row.endpoint,
            "tools": row.tools,
            "enabledTools": row.enabled_tools,
            "toolsMeta": row.tools_meta,  # 도구 메타(스펙 151) — 상세 드로어 카드용
            "status": row.status,
            "published": row.published,
            "served_url": _mcp_served_url(row),  # 서빙 URL(스펙 156) — custom+정의보유만, 그 외 None
            "auth": _mcp_auth_masked(row),
            "usedBy": _count_by(agents, "mcps", row.name),
            "updated": "—",
            "owner_id": row.owner_id,  # 스펙 112
            "can_manage": may_manage(row.owner_id, principal),  # 스펙 114 — UI 편집/삭제 표시 파생
        }
        for row in mcp_servers
    ]

    return {
        "persona": {**_CATEGORY_META["persona"], "items": persona_items},
        "memory": {**_CATEGORY_META["memory"], "items": memory_items},
        "embedding": {**_CATEGORY_META["embedding"], "items": embedding_items},
        "mcp": {**_CATEGORY_META["mcp"], "items": mcp_items},
    }
