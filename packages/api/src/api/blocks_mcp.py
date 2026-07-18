"""MCP 서버 라우트 — blocks.py에서 분할(스펙 393 P4).

update_mcp_server(구 CC 14)는 정책 검증 함수 3개(source 불변·rename 가드·auth 패치)로,
_validate_tool_testable(구 CC 11)은 술어 3개로 분해(codex 자문). 참조 스캔은
references.agents_referencing_mcp_tools로 상향. 파사드는 blocks.py(재수출 계약).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto
from .auth import current_principal
from .block_versions import delete_block_history, record_block_version
from .blocks_mcp_discovery import _live_discover, _tools_meta_from_details
from .blocks_presenters import mcp_to_out
from .blocks_shared import _commit_or_409, _norm_description
from .db import get_or_404, get_session
from .models import McpServer, User
from .naming import assert_valid_name
from .ownership import assert_may_manage, may_manage, owner_of
from .references import (
    agents_referencing,
    agents_referencing_mcp_tools,
    referenced_message,
)
from .schemas import (
    McpDiscoverIn,
    McpDiscoverResult,
    McpPublishIn,
    McpServerIn,
    McpServerOut,
    McpToolTestIn,
    McpToolTestOut,
)

router = APIRouter(tags=["blocks"])


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
    있으면 409(rename/삭제 가드와 같은 operation-symmetry). 스캔은 references로 상향(스펙 393)."""
    removed = [t for t in (obj.enabled_tools or []) if t not in set(new_tools)]
    if not removed:
        return
    refs = await agents_referencing_mcp_tools(session, obj.name, removed)
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


def _assert_tool_enabled(obj: McpServer, tool_name: str) -> None:
    """시험 대상은 활성 도구여야(스펙 326)."""
    if tool_name not in (obj.enabled_tools or []):
        raise HTTPException(status_code=400, detail=f"활성 도구가 아닙니다: {tool_name}")


def _assert_tool_transport(obj: McpServer) -> None:
    """http transport + URL 보유 서버만 시험 가능(스펙 326)."""
    if obj.transport != "http" or not (obj.url or obj.endpoint):
        raise HTTPException(
            status_code=400, detail="http transport + URL이 있는 서버만 시험할 수 있습니다."
        )


def _assert_tool_confirm(obj: McpServer, tool_name: str, confirm: bool) -> None:
    """승인 정책 도구는 confirm 없이 400 — 시험 통로가 HIL을 소리 없이 우회하지 않게 백엔드 강제."""
    approval = ((obj.tools_meta or {}).get(tool_name) or {}).get("approval") or {}
    if approval.get("required") and not confirm:
        raise HTTPException(
            status_code=400,
            detail="승인 정책이 걸린 도구입니다 — 부수효과를 확인하고 confirm으로 재시도하세요.",
        )


def _validate_tool_testable(obj: McpServer, tool_name: str, confirm: bool) -> None:
    """도구 시험 사전 검증(스펙 326) — 활성 도구·http transport·승인 confirm 세 술어(스펙 393 분해)."""
    _assert_tool_enabled(obj, tool_name)
    _assert_tool_transport(obj)
    _assert_tool_confirm(obj, tool_name, confirm)


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


def _assert_source_immutable(data: dict, obj: McpServer) -> None:
    """source(유래)는 생성 후 불변(스펙 152, codex High) — external→local 세탁 후 publish하는
    재공개 우회를 봉인. provenance는 등록 시점의 사실이지 편집 대상이 아니다."""
    if data.get("source") and data["source"] != obj.source:
        raise HTTPException(status_code=400, detail="source(유래)는 생성 후 변경할 수 없습니다.")


async def _assert_renameable(session: AsyncSession, obj: McpServer, new_name: str) -> None:
    """이름 변경 가드(스펙 093/148/360) — 이름 규칙·예약 서빙 이름·참조 무결성(409).

    런타임은 McpServer.name.in_(config["mcps"])로 해석하므로 참조 중인 서버 name을 바꾸면 옛 name이
    dangling 되어 도구가 조용히 사라진다 → 참조가 있으면 rename을 409로 막는다(값은 옛 name 기준)."""
    assert_valid_name(new_name)  # 이름 변경 시에만 규칙(기존은 grandfather, 스펙 148)
    from . import served_mcp

    if new_name in served_mcp.SERVED_MCPS:
        # 예약 서빙 이름 개명 차단(스펙 360, codex 방어심화) — 생성 게이트와 대칭.
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


def _apply_auth_patch(obj: McpServer, auth_in: str | None) -> None:
    """auth 의미 구분(provider.api_key와 동형): None/마스킹 = 기존 암호화 토큰 보존,
    빈 문자열 = 명시적 제거, 그 외 = 새 평문 암호화. 마스킹값이 그대로 저장되는 버그 방지."""
    if auth_in is None or crypto.is_masked(auth_in):
        return  # 보존
    obj.auth = None if auth_in == "" else crypto.encrypt(auth_in)


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
    _assert_source_immutable(data, obj)
    # published=커스텀 외부 서빙 전용(스펙 211, 152 재공개 금지 포함) — 끄기는 항상 허용.
    if data.get("published") and obj.source != "custom":
        raise HTTPException(status_code=400, detail="외부 서빙은 커스텀 MCP만 켤 수 있습니다.")
    if data.get("tools_meta") is None:
        data.pop("tools_meta", None)  # None=미변경(스펙 151 — 편집 폼이 메타를 안 들고 있어도 보존)
    # 참조 무결성(스펙 093, operation-symmetry): rename도 삭제와 똑같이 config의 name 링크를 끊는다.
    new_name = data.get("name")
    if new_name is not None and new_name != obj.name:
        await _assert_renameable(session, obj, new_name)
    auth_in = data.pop("auth", None)
    for key, value in data.items():
        setattr(obj, key, value)
    _apply_auth_patch(obj, auth_in)
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
