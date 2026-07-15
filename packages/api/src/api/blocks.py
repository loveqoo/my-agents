"""빌딩 블록 카탈로그 CRUD + 관리자 UI 집계 (REST).

프롬프트·메모리타입·MCP 서버의 전체 CRUD와, 관리자 콘솔이 한 번에 읽는 4개
카테고리 집계(`GET /blocks`)를 제공한다. embedding 카테고리는 RAG 컬렉션(스펙 036)을
읽기 전용으로 비춘다 — 컬렉션 CRUD/인제스트는 `rag.py`(`/collections`)가 담당한다.
"""

import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.runtime import is_first_party

from . import crypto
from .auth import current_principal
from .block_versions import BLOCK_KINDS, delete_block_history, record_block_version
from .db import get_or_404, get_session
from .models import Agent, BlockVersion, Collection, McpServer, MemoryType, Prompt, User
from .naming import assert_valid_name
from .ownership import assert_may_manage, may_manage, may_use_agent, owner_of
from .references import _config_has, agents_referencing, referenced_message
from .schemas import (
    BlockVersionOut,
    McpDiscoverIn,
    McpDiscoverResult,
    McpPublishIn,
    McpServerIn,
    McpServerOut,
    McpToolTestIn,
    McpToolTestOut,
    MemoryTypeIn,
    MemoryTypeOut,
    PromptApplyIn,
    PromptApplyOut,
    PromptIn,
    PromptOut,
    PromptUsageAgentOut,
)
from .serializers import _iso, audit_of

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

router = APIRouter(tags=["blocks"])


def _norm_description(data: dict) -> dict:
    """설명 정규화 — 공백뿐이면 None(스펙 148, 210)."""
    if "description" in data:
        data["description"] = (data["description"] or "").strip() or None
    return data


async def _commit_or_409(session: AsyncSession, detail: str) -> None:
    """이름 유니크 충돌을 500 대신 409로(스펙 148 — name unique 테이블 공용)."""
    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail) from err


# ----------------------------- 프롬프트 -----------------------------
@router.get("/prompts", response_model=list[PromptOut])
async def list_prompts(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(Prompt))
    return result.scalars().all()


@router.post("/prompts", response_model=PromptOut, status_code=201)
async def create_prompt(body: PromptIn, session: AsyncSession = Depends(get_session)) -> Any:
    assert_valid_name(body.name)  # 식별 이름 규칙(스펙 148)
    obj = Prompt(**_norm_description(body.model_dump()))
    session.add(obj)
    await _commit_or_409(session, "같은 식별 이름의 프롬프트가 이미 있습니다.")
    await session.refresh(obj)
    await record_block_version(session, "prompt", obj)  # v1 이력(스펙 369)
    await session.commit()
    return obj


@router.get("/prompts/{id}", response_model=PromptOut)
async def get_prompt(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    return await get_or_404(session, Prompt, id)


@router.put("/prompts/{id}", response_model=PromptOut)
async def update_prompt(
    id: uuid.UUID, body: PromptIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await get_or_404(session, Prompt, id)
    if body.name != obj.name:
        assert_valid_name(body.name)  # 이름 변경 시에만 규칙(기존은 grandfather, 스펙 148)
        # rename도 config["prompt"] 참조를 깬다 — MCP(093)와 동일 가드(codex 148 High)
        refs = await agents_referencing(session, "prompt", obj.name)
        if refs:
            raise HTTPException(
                status_code=409, detail=referenced_message(refs, "프롬프트", action="이름 변경")
            )
    for key, value in _norm_description(body.model_dump()).items():
        setattr(obj, key, value)
    # 콘텐츠 변경이면 버전+1 + 이력 append(스펙 369 관문) — 동시 편집 레이스는 UNIQUE가 commit서 막음.
    await record_block_version(session, "prompt", obj)
    await _commit_or_409(session, "같은 식별 이름의 프롬프트가 이미 있거나 동시 편집과 겹쳤습니다.")
    await session.refresh(obj)
    return obj


@router.get("/prompts/{id}/agents", response_model=list[PromptUsageAgentOut])
async def prompt_agents(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    """이 프롬프트를 쓰는 에이전트 + 각 오래됨(stale) 상태(스펙 161). 편집 화면이 "N개 사용·M개
    오래됨"과 선택 반영 대상을 그린다. stale = 에이전트 스냅샷(agent.prompt) != 현재 본문(obj.body)."""
    obj = await get_or_404(session, Prompt, id)
    agents = (await session.execute(select(Agent))).scalars().all()
    return [
        PromptUsageAgentOut(
            id=a.id,
            agentId=a.agent_id,
            name=a.name,
            description=a.description,
            stale=(a.prompt != obj.body),
            canManage=may_manage(a.owner_id, principal),
        )
        for a in agents
        # may_use_agent 가시성 필터(스펙 147, codex 161 High) — 타인 private 에이전트의 식별자·stale를
        # 누출하지 않는다(일반 list/get/chat과 동일 게이트). admin/machine은 전부, member는 본인+public.
        if is_first_party(a.source)
        and may_use_agent(a, principal)
        and _config_has(a.config, "prompt", obj.name)
    ]


@router.post("/prompts/{id}/apply", response_model=PromptApplyOut)
async def prompt_apply(
    id: uuid.UUID,
    body: PromptApplyIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    """선택 에이전트들의 프롬프트 스냅샷을 이 프롬프트 최신 본문으로 반영(스펙 161). **각 에이전트
    can_manage 게이트** — 관리 불가/이 프롬프트 미참조 대상은 건너뛴다(남의 에이전트 무단 변경 금지)."""
    obj = await get_or_404(session, Prompt, id)
    want = set(body.agentIds)
    agents = (await session.execute(select(Agent).where(Agent.id.in_(want)))).scalars().all()
    applied: list[uuid.UUID] = []
    skipped: list[uuid.UUID] = []
    found = {a.id for a in agents}
    # 스펙 370: in-place 스냅샷 갱신(구 161)은 불변 버전 모델과 비정합(오픈 버전 동작이 버전 없이
    # 바뀜) → **채택 스크래치 생성**으로 재구현. 반영은 각 에이전트에서 오픈해야 서빙된다(명시적).
    from sqlalchemy.orm import selectinload as _sl

    from .block_versions import freeze_pins
    from .models import AgentVersion as _AV

    for agent in agents:
        if (
            is_first_party(agent.source)
            and _config_has(agent.config, "prompt", obj.name)
            and may_manage(agent.owner_id, principal)
        ):
            from .agents.helpers import _today, scratch_target

            loaded = (
                await session.execute(
                    select(Agent).where(Agent.id == agent.id).options(_sl(Agent.versions))
                )
            ).scalar_one()
            scratch, target_ver = scratch_target(loaded)
            base = next(
                (v for v in loaded.versions if v.version == loaded.active_version), None
            )
            cfg = dict((base.config if base is not None else loaded.config) or {})
            pins = await freeze_pins(session, cfg)
            if scratch is not None:
                scratch.version = target_ver
                scratch.config = cfg
                scratch.pins = pins
                scratch.note = f"프롬프트 새 버전 채택 {_today()}"
            else:
                loaded.versions.append(
                    _AV(
                        version=target_ver,
                        ever_opened=False,
                        pins=pins,
                        note=f"프롬프트 새 버전 채택 {_today()}",
                        config=cfg,
                    )
                )
            applied.append(agent.id)
        else:
            skipped.append(agent.id)
    skipped.extend(aid for aid in want if aid not in found)  # 미존재도 skip으로 정직 보고
    if applied:
        await session.commit()
    return PromptApplyOut(applied=applied, skipped=skipped)


@router.delete("/prompts/{id}", status_code=204)
async def delete_prompt(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await get_or_404(session, Prompt, id)
    # 참조 중 삭제 차단(093 operation-symmetry를 프롬프트에도 — codex 148 High): 지우면
    # resolve_prompt가 name 문자열 자체를 시스템 프롬프트로 쓰는 조용한 degrade가 생긴다.
    refs = await agents_referencing(session, "prompt", obj.name)
    if refs:
        raise HTTPException(status_code=409, detail=referenced_message(refs, "프롬프트"))
    await delete_block_history(session, "prompt", obj.id)  # 폴리모픽 이력 동일 tx 정리(스펙 369)
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
    await _commit_or_409(session, "같은 key의 메모리 타입이 이미 있습니다.")
    await session.refresh(obj)
    await record_block_version(session, "memory-type", obj)  # v1 이력(스펙 369)
    await session.commit()
    return obj


@router.get("/memory-types/{id}", response_model=MemoryTypeOut)
async def get_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    return await get_or_404(session, MemoryType, id)


@router.put("/memory-types/{id}", response_model=MemoryTypeOut)
async def update_memory_type(
    id: uuid.UUID, body: MemoryTypeIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await get_or_404(session, MemoryType, id)
    for key, value in body.model_dump().items():
        setattr(obj, key, value)
    await record_block_version(session, "memory-type", obj)  # 스펙 369 관문
    await _commit_or_409(session, "동시 편집과 겹쳤습니다 — 다시 시도하세요.")
    await session.refresh(obj)
    return obj


@router.delete("/memory-types/{id}", status_code=204)
async def delete_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await get_or_404(session, MemoryType, id)
    await delete_block_history(session, "memory-type", obj.id)  # 스펙 369
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


def _tool_info(t: "BaseTool") -> dict:
    """langchain 도구 객체 → {name, description, params[{name,type,required}]} (스펙 151).
    스키마 파생 실패는 params=[]로 접는다(표시용 — 탐색 자체를 죽이지 않는다). 순수 함수."""
    params: list[dict] = []
    try:
        props = dict(getattr(t, "args", None) or {})
        required: set[str] = set()
        try:
            schema = t.tool_call_schema
            js = (
                schema.model_json_schema()
                if hasattr(schema, "model_json_schema")
                else (schema or {})
            )
            required = set(js.get("required") or [])
        except Exception:
            pass
        for pname, ps in list(props.items())[:_TOOL_PARAMS_CAP]:
            ptype = "any"
            if isinstance(ps, dict):
                if isinstance(ps.get("type"), str):
                    ptype = ps["type"]
                elif isinstance(ps.get("anyOf"), list):
                    ptype = (
                        "/".join(
                            str(x.get("type", "?")) for x in ps["anyOf"] if isinstance(x, dict)
                        )
                        or "any"
                    )
            params.append(
                {"name": str(pname)[:80], "type": str(ptype)[:40], "required": pname in required}
            )
    except Exception:
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
    for detail in details[:_TOOLS_META_CAP]:
        name = detail.get("name")
        if not name:
            continue
        entry = {"description": detail.get("description", ""), "params": detail.get("params", [])}
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


def _audit_json(row: object) -> dict:
    """감사 4값을 JSON 직렬화 가능한 형태로(블록 목록은 dict를 직접 조립한다 — 스펙 344).
    datetime은 ISO 문자열로, actor는 **문자열 그대로**(user 테이블 resolve 금지 — 스펙 343 전제)."""
    return {
        "created_at": _iso(getattr(row, "created_at", None)),
        "updated_at": _iso(getattr(row, "updated_at", None)),
        "created_by": getattr(row, "created_by", None),
        "updated_by": getattr(row, "updated_by", None),
    }


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
        version=obj.version,  # 스펙 369
        **audit_of(obj),  # 감사 4값(스펙 344)
    )


@router.get("/mcp-servers", response_model=list[McpServerOut])
async def list_mcp_servers(
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    result = await session.execute(select(McpServer))
    outs = [mcp_to_out(o) for o in result.scalars().all()]
    for out in outs:  # 스펙 114 — 관리 가능 여부 파생
        out.can_manage = may_manage(out.owner_id, principal)
    return outs


@router.post("/mcp-servers", response_model=McpServerOut, status_code=201)
async def create_mcp_server(
    body: McpServerIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    assert_valid_name(body.name)  # 식별 이름 규칙(스펙 148) — 서버 등록명은 사용자가 짓는다
    from . import served_mcp

    if body.name in served_mcp.SERVED_MCPS:
        # 서빙 예약 이름(스펙 156) — 사용자가 서빙 레지스트리 이름(calc-tools 등)을 어떤 source로도
        # 선점하지 못하게 한다(선점 시 시스템 reconcile이 그 이름을 못 만들어 서빙이 막히는 스쿼팅 차단).
        raise HTTPException(
            status_code=400, detail="예약된 서빙 MCP 이름입니다 — 다른 이름을 쓰세요."
        )
    if body.source == "custom":
        # 커스텀(내부 코드 정의) MCP는 **시스템 전용**(스펙 156, codex High) — provenance를 자가선언해
        # 내부 레지스트리 이름(calc-tools 등)을 선점·공개하는 우회를 봉인한다. custom 행은 오직 seed의
        # 멱등 reconcile만 만든다(owner_id=None). 사용자는 local/external만 등록. (152 유래-불변 계열)
        raise HTTPException(
            status_code=400,
            detail="커스텀(내부 정의) MCP는 시스템 전용입니다 — 사용자가 생성할 수 없습니다.",
        )
    if body.published and body.source != "custom":
        # published=커스텀 외부 서빙 전용(스펙 211, 152 재공개 금지 포함). 사용자는 custom 생성이
        # 불가하므로(위 게이트) 사실상 생성 경로에서 published=true는 항상 400.
        raise HTTPException(status_code=400, detail="외부 서빙은 커스텀 MCP만 켤 수 있습니다.")
    data = _norm_description(body.model_dump())
    data["enabled_tools"] = body.enabled_tools or body.tools
    # auth는 평문 입력 → Fernet 암호화 저장. 마스킹값이 들어오면(신규엔 없어야 함) 비워둔다.
    data["auth"] = (
        None if (body.auth and crypto.is_masked(body.auth)) else crypto.encrypt(body.auth)
    )
    data["owner_id"] = owner_of(principal)  # 생성 시 1회 스탬프(스펙 112)
    obj = McpServer(**data)
    session.add(obj)
    await _commit_or_409(session, "같은 식별 이름의 MCP 서버가 이미 있습니다.")
    await session.refresh(obj)
    await record_block_version(session, "mcp-server", obj)  # v1 이력(스펙 369)
    await session.commit()
    return mcp_to_out(obj)


async def _live_discover(url: str, token: str | None) -> McpDiscoverResult:
    """MCP 라이브 탐색 공유 코어(스펙 054 E·151) — SSRF guard → 연결 → 이름+메타.
    discover(폼, 평문/마스킹 토큰)와 rediscover(저장 서버, 복호 토큰)가 공유(드리프트 0).
    SsrfBlockedError는 HTTPException 400으로 올린다(보안 경계 ≠ 정상 연결실패)."""
    import asyncio
    import time

    from langchain_mcp_adapters.client import MultiServerMCPClient

    from . import net_guard

    try:
        await net_guard.refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064)
        net_guard.guard_url(url)
    except net_guard.SsrfBlockedError as exc:
        # 보안 경계 위반은 4xx(정상 연결실패의 ok=False와 구분) — 스펙 054 완료조건 ④.
        raise HTTPException(status_code=400, detail=str(exc)) from None

    headers = {"Authorization": f"Bearer {token}"} if token else None
    t0 = time.perf_counter()
    try:
        client = MultiServerMCPClient(
            {
                "probe": {
                    "transport": "streamable_http",
                    "url": url,
                    "headers": headers,
                    # 리다이렉트-SSRF 차단(적대 리뷰 H1) — runtime.build_mcp_tools와 동일 정책.
                    "httpx_client_factory": net_guard.mcp_http_client_factory,
                }
            }
        )
        async with asyncio.timeout(15):
            tools = await client.get_tools(server_name="probe")
    except Exception:
        ms = int((time.perf_counter() - t0) * 1000)
        return McpDiscoverResult(ok=False, reachable=False, latencyMs=ms, detail="연결 실패")
    ms = int((time.perf_counter() - t0) * 1000)
    names = [t.name for t in tools]
    # 메타(설명·파라미터, 스펙 151) — dict를 pydantic이 McpToolInfo로 검증·강제(모델 생성 시).
    details: list[Any] = [_tool_info(t) for t in tools[:_TOOLS_META_CAP]]
    return McpDiscoverResult(
        ok=True,
        reachable=True,
        tools=names,
        toolsDetail=details,
        latencyMs=ms,
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


async def _assert_removed_tools_unreferenced(
    session: AsyncSession, obj: McpServer, new_tools: list[str]
) -> None:
    """재탐색으로 사라질 도구를 참조하는 에이전트가 있으면 409(없으면 통과).

    참조 보호(codex 151 Medium): 원격이 일시적으로 도구를 빠뜨리면 재탐색 한 번에 에이전트의
    툴 단위 능력(`mcp:{서버}/{도구}`)이 조용히 사라진다 — 제거될 도구를 참조하는 에이전트가
    있으면 409(rename/삭제 가드와 같은 operation-symmetry)."""
    removed = [t for t in (obj.enabled_tools or []) if t not in set(new_tools)]
    if not removed:
        return
    agents = list((await session.execute(select(Agent))).scalars().all())
    refs = []
    for agent in agents:
        caps = (agent.config or {}).get("capabilities") if isinstance(agent.config, dict) else None
        if isinstance(caps, list) and any(f"mcp:{obj.name}/{t}" in caps for t in removed):
            refs.append({"agent": agent.name, "where": "active"})
    if refs:
        raise HTTPException(
            status_code=409,
            detail=referenced_message(
                refs, f"MCP 도구({', '.join(removed[:5])})", action="재탐색(도구 제거)"
            ),
        )


@router.post("/mcp-servers/{id}/rediscover", response_model=McpServerOut)
async def rediscover_mcp_server(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    """저장된 MCP 서버의 도구·메타를 재탐색해 갱신(스펙 151 — 상세 화면 '도구 정보 새로 탐색').

    저장된 자격증명을 **백엔드에서 복호**해 쓴다(프론트는 마스킹 토큰만 가져 재탐색 불가).
    enabled_tools는 새 목록과의 교집합으로 보존(사라진 도구만 떨어냄 — 임의 활성화 없음)."""
    obj = await get_or_404(session, McpServer, id)
    assert_may_manage(obj, principal)  # 소유자/특권만(스펙 112)
    if obj.transport != "http" or not obj.url:
        raise HTTPException(
            status_code=400, detail="http transport + URL이 있는 서버만 재탐색할 수 있습니다."
        )
    token = crypto.decrypt(obj.auth) if obj.auth else None
    result = await _live_discover(obj.url, token)
    if not result.ok:
        raise HTTPException(status_code=502, detail=f"재탐색 실패 — {result.detail}")
    await _assert_removed_tools_unreferenced(session, obj, result.tools)
    obj.tools = result.tools
    # 기존 tools_meta를 넘겨 관리자 승인 정책(approval, 스펙 177)을 이월 보존 — 재탐색이 게이트를 지우지 않게.
    obj.tools_meta = _tools_meta_from_details(
        [d.model_dump() for d in result.toolsDetail], obj.tools_meta
    )
    obj.enabled_tools = [t for t in (obj.enabled_tools or []) if t in result.tools]
    obj.status = "connected"
    # 재탐색도 콘텐츠 변경(tools/tools_meta — 에이전트 동작 결정) → 버전 관문 경유(스펙 369).
    # 도구 무변경 재탐색은 payload 동일이라 자동 no-op.
    await record_block_version(session, "mcp-server", obj)
    await _commit_or_409(session, "동시 편집과 겹쳤습니다 — 다시 시도하세요.")
    await session.refresh(obj)
    return mcp_to_out(obj)


def _validate_tool_testable(obj: McpServer, tool_name: str, confirm: bool) -> None:
    """도구 시험 사전 검증(스펙 326) — 활성 도구·http transport·승인 정책 confirm 게이트.
    승인 도구는 confirm 없이 400(시험 통로가 HIL을 소리 없이 우회하지 않게 백엔드 강제)."""
    if tool_name not in (obj.enabled_tools or []):
        raise HTTPException(status_code=400, detail=f"활성 도구가 아닙니다: {tool_name}")
    if obj.transport != "http" or not (obj.url or obj.endpoint):
        raise HTTPException(
            status_code=400, detail="http transport + URL이 있는 서버만 시험할 수 있습니다."
        )
    approval = ((obj.tools_meta or {}).get(tool_name) or {}).get("approval") or {}
    if approval.get("required") and not confirm:
        raise HTTPException(
            status_code=400,
            detail="승인 정책이 걸린 도구입니다 — 부수효과를 확인하고 confirm으로 재시도하세요.",
        )


def _build_test_server(obj: McpServer, tool_name: str) -> dict:
    """build_mcp_tools에 넘길 시험용 서버 dict(스펙 326) — 승인 래핑 비활성 사본(원본 무변경).
    approval 키를 지우면 리졸버의 **레거시 폴백**(_APPROVAL_ACTIONS — delete_record 등)이 되살아나
    그래프 밖 interrupt()로 터지므로, {required: False} **명시 덮어쓰기**로 꺼야 한다(스펙 177 우선순위).
    시험은 confirm 게이트가 승인 역할을 대신한다."""
    meta = dict(obj.tools_meta or {})
    stripped_meta = {
        t: {**(m or {}), "approval": {"required": False}} for t, m in meta.items()
    } or {tool_name: {"approval": {"required": False}}}
    token = None if crypto.is_masked(obj.auth) else crypto.decrypt(obj.auth)
    return {
        "name": obj.name,
        "url": obj.url or obj.endpoint or "",
        "transport": obj.transport or "http",
        "enabled_tools": [tool_name],  # 시험 대상만 빌드(불필요 래핑 생략)
        "auth_token": token,
        "tools_meta": stripped_meta,
    }


@router.post("/mcp-servers/{id}/test-tool", response_model=McpToolTestOut)
async def test_mcp_tool(
    id: uuid.UUID,
    body: McpToolTestIn,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """저장된 MCP 서버의 도구를 **실제로 호출**해 본다(스펙 326 — 상세 드로어 '도구 시험').

    실행 경로는 채팅과 같은 `build_mcp_tools`를 재사용한다(새 연결 코드 금지) — SSRF 가드·
    allowed_hosts·자격증명 복호·어댑터 swallow 해제·결과/사유 마스킹+캡(스펙 320)이 전부 그
    경로에 이미 산다. 결과는 래퍼의 calls_sink에서 회수(직접 반환값이 아니라 **채팅이 기록하는
    것과 동일한 표면**을 보여준다 — 시험이 곧 실전 리허설).

    승인 정책(스펙 177) 도구는 confirm=True 없이 400 — 시험 통로가 HIL을 소리 없이 우회하지
    않게 백엔드에서 강제. 승인 래핑 자체는 tools_meta에서 approval을 걷어낸 사본으로 비활성화
    (그래프 밖 interrupt() 불가 — confirm 게이트가 그 자리를 대신한다).

    연결 실패·도구 미발견은 조용한 스킵 대신 원인 명시(스펙 322 footgun의 시험판 방지)."""
    from .runtime import build_mcp_tools

    obj = await get_or_404(session, McpServer, id)
    tool_name = (body.tool or "").strip()
    _validate_tool_testable(obj, tool_name, bool(body.confirm))
    server = _build_test_server(obj, tool_name)
    calls_sink: list[dict] = []
    tools = await build_mcp_tools([server], calls_sink)
    if not tools:
        # 조용한 스킵을 말로 — SSRF 차단/연결 실패/도구 미발견을 사용자가 구분해 조치할 수 있게.
        raise HTTPException(
            status_code=502,
            detail=f"도구를 가져오지 못했습니다 — 서버({obj.name}) 연결 실패 또는 원격에 {tool_name} 없음. '도구 정보 새로 탐색'으로 상태를 확인하세요.",
        )
    try:
        await tools[0].ainvoke(body.args or {})
    except Exception as exc:
        # 래퍼 밖 실패 = 인자 스키마 검증(StructuredTool이 _run 이전에 검사) 등 — 500 대신
        # 시험 결과로 표면화(인자 틀림도 정당한 시험 결과다). 마스킹+캡은 채팅 표면과 동일 규칙.
        from .runtime import _ERR_CAP, _sanitize_preview

        etype = type(exc).__name__.lstrip("_")
        return McpToolTestOut(ok=False, error=_sanitize_preview(f"{etype}: {exc}", _ERR_CAP))
    rec = calls_sink[-1] if calls_sink else {}
    return McpToolTestOut(
        ok=rec.get("status") == "ok",
        ms=int(rec.get("ms") or 0),
        result=rec.get("result"),
        error=rec.get("error"),
    )


@router.get("/mcp-servers/{id}", response_model=McpServerOut)
async def get_mcp_server(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await get_or_404(session, McpServer, id)
    return mcp_to_out(obj)


@router.put("/mcp-servers/{id}", response_model=McpServerOut)
async def update_mcp_server(
    id: uuid.UUID,
    body: McpServerIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    obj = await get_or_404(session, McpServer, id)
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
        assert_valid_name(new_name)  # 이름 변경 시에만 규칙(기존은 grandfather, 스펙 148)
        from . import served_mcp

        if new_name in served_mcp.SERVED_MCPS:
            # 예약 서빙 이름 개명 차단(스펙 360, codex 방어심화) — 생성 게이트(위 371줄)와 대칭.
            # 시스템 served 행이 지워진 틈에 사용자 행을 served 이름으로 개명해 SSRF 예외 대상으로
            # 만드는 우회를 봉인한다(그래도 url이 정확 served_url이어야 예외라 임의 내부주소는 불가).
            raise HTTPException(
                status_code=400, detail="예약된 서빙 MCP 이름입니다 — 다른 이름을 쓰세요."
            )
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
    # auth(비밀)는 payload 제외라 auth-only 변경은 버전 무증가(스펙 369 §2 경계).
    await record_block_version(session, "mcp-server", obj)
    await _commit_or_409(session, "같은 식별 이름의 MCP 서버가 이미 있거나 동시 편집과 겹쳤습니다.")
    await session.refresh(obj)
    return mcp_to_out(obj)


@router.delete("/mcp-servers/{id}", status_code=204)
async def delete_mcp_server(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> None:
    obj = await get_or_404(session, McpServer, id)
    assert_may_manage(obj, principal)  # 소유자/특권만(스펙 112)
    # 참조 무결성(스펙 093): 이 서버 name을 config에 담은 에이전트가 있으면 삭제 차단.
    # 삭제하면 config에 dangling name만 남아 런타임이 조용히 도구 없이 동작한다.
    refs = await agents_referencing(session, "mcps", obj.name)
    if refs:
        raise HTTPException(status_code=409, detail=referenced_message(refs, "MCP 서버"))
    await delete_block_history(session, "mcp-server", obj.id)  # 스펙 369
    await session.delete(obj)
    await session.commit()


@router.put("/mcp-servers/{id}/publish", response_model=McpServerOut)
async def publish_mcp_server(
    id: uuid.UUID,
    body: McpPublishIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    obj = await get_or_404(session, McpServer, id)
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
    "prompt": {
        "label": "프롬프트",
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
    principal: User | str = Depends(current_principal),
) -> dict[str, Any]:
    agents = list((await session.execute(select(Agent))).scalars().all())

    prompts = list((await session.execute(select(Prompt))).scalars().all())
    memory_types = list((await session.execute(select(MemoryType))).scalars().all())
    collections = list(
        (
            await session.execute(
                select(Collection).options(selectinload(Collection.embedding_model))
            )
        )
        .scalars()
        .all()
    )
    mcp_servers = list((await session.execute(select(McpServer))).scalars().all())

    prompt_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,  # 설명(스펙 210)
            "tone": row.tone,
            "body": row.body,
            "usedBy": _count_by(agents, "prompt", row.name, scalar=True),
            "updated": _iso(row.updated_at),  # 수정일 배선(스펙 216) — 프론트 fmtTime이 친화 표기
            "version": row.version,  # 스펙 369
            **_audit_json(row),  # 감사 4값(스펙 344)
        }
        for row in prompts
    ]
    memory_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "key": row.key,
            "scope": row.scope,
            "body": row.body,
            "usedBy": _count_by(agents, "memories", row.name),
            "updated": "—",  # 메모리 타입은 읽기 전용(시스템 enum, spec 016) — 수정 N/A(스펙 216)
            **_audit_json(row),  # 감사 4값(스펙 344)
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
            **_audit_json(row),  # 감사 4값(스펙 344)
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
            "served_url": _mcp_served_url(
                row
            ),  # 서빙 URL(스펙 156) — custom+정의보유만, 그 외 None
            "auth": _mcp_auth_masked(row),
            **_audit_json(row),  # 감사 4값(스펙 344)
            "usedBy": _count_by(agents, "mcps", row.name),
            "updated": _iso(row.updated_at),  # 수정일 배선(스펙 216)
            "version": row.version,  # 스펙 369
            "owner_id": row.owner_id,  # 스펙 112
            "can_manage": may_manage(row.owner_id, principal),  # 스펙 114 — UI 편집/삭제 표시 파생
        }
        for row in mcp_servers
    ]

    return {
        "prompt": {**_CATEGORY_META["prompt"], "items": prompt_items},
        "memory": {**_CATEGORY_META["memory"], "items": memory_items},
        "embedding": {**_CATEGORY_META["embedding"], "items": embedding_items},
        "mcp": {**_CATEGORY_META["mcp"], "items": mcp_items},
    }


# ----------------------------- 블록 버전 이력(스펙 369) -----------------------------
@router.get("/block-versions/{kind}/{block_pk}", response_model=list[BlockVersionOut])
async def list_block_versions(
    kind: str, block_pk: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Any:
    """블록 이력 목록(최신순) — 5종 공유 제네릭(스펙 369 §4). kind 오탈자는 404."""
    if kind not in BLOCK_KINDS:
        raise HTTPException(status_code=404, detail=f"알 수 없는 블록 종류: {kind}")
    rows = await session.execute(
        select(BlockVersion)
        .where(BlockVersion.kind == kind, BlockVersion.block_pk == block_pk)
        .order_by(BlockVersion.version.desc())
    )
    return rows.scalars().all()


@router.get("/block-versions/{kind}/{block_pk}/{version}", response_model=BlockVersionOut)
async def get_block_version(
    kind: str, block_pk: uuid.UUID, version: int, session: AsyncSession = Depends(get_session)
) -> Any:
    if kind not in BLOCK_KINDS:
        raise HTTPException(status_code=404, detail=f"알 수 없는 블록 종류: {kind}")
    row = await session.scalar(
        select(BlockVersion).where(
            BlockVersion.kind == kind,
            BlockVersion.block_pk == block_pk,
            BlockVersion.version == version,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="그 버전의 이력이 없습니다.")
    return row
