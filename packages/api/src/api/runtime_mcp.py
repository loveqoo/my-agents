"""MCP 도구 런타임(연결·승인 리졸버·래핑·사양 캐시) — runtime.py에서 분할(스펙 397 P5).

resolve_tool_approval(구 CC 13)은 기본 해석(_base_approval)·오버라이드(_apply_approval_override)
추출로 **우선순위(tools_meta 기본 > 레거시 폴백 > tool_policy 오버라이드)를 함수 경계로 표면화**
(의미 동결 — 브로커 McpProvider가 이 리졸버를 공유, 드리프트 0). build_mcp_tools(구 CC 17)는
연결 준비(_prepare_connections)·서버별 래핑(_tools_from_raw) 추출로 분해.
파사드는 runtime.py(재수출 계약).
"""

import asyncio
import contextlib
import hashlib
import logging
import re
import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt

from .runtime_trace_safety import (
    _ERR_CAP,
    _RESULT_CAP,
    _content_text,
    _redact_args,
    _sanitize_preview,
    _sink_from,
)

log = logging.getLogger("api.runtime")


def _safe_name(server: str, tool_name: str) -> str:
    """LLM 툴 이름 제약([A-Za-z0-9_-])에 맞게 정규화. 원래 server/tool은 트레이스에 유지."""
    raw = f"{server}__{tool_name}"
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:60]
    return safe or "tool"


# HIL 승인 게이트 정책(스펙 041) — approver=admin 권한에 묶인 (server, tool) 도구만.
# 이 도구를 ReAct가 호출하면 **실 부수효과(rt.ainvoke) 이전에** langgraph interrupt로 그래프가
# 일시정지되고, admin 승인 전에는 절대 실행되지 않는다(핵심 불변식). 정책은 코드 한 곳 — verify로 핀.
# 키는 (McpServer.name, 도구이름). seed가 이 서버/도구를 노출한다.
# "local-tools"는 mock_mcp.MOCK_MCP_SERVER_NAME — verify 테스트가 두 상수의 일치를 단언한다(drift 방지).
_APPROVAL_ACTIONS: dict[tuple[str, str], str] = {
    ("local-tools", "delete_record"): "data.delete",
}


def _base_approval(server: str, tool: str, tools_meta: dict | None) -> tuple[bool, str, str]:
    """도구 기본 승인(스펙 177 P1) — tools_meta[tool].approval(관리자 데이터) 우선, 없으면 레거시
    _APPROVAL_ACTIONS 폴백(무회귀). 반환 (required, approver, permission)."""
    meta = tools_meta.get(tool) if isinstance(tools_meta, dict) else None
    base = meta.get("approval") if isinstance(meta, dict) else None
    if isinstance(base, dict):
        return bool(base.get("required")), base.get("approver") or "admin", f"mcp.{server}.{tool}"
    # 레거시 폴백(tools_meta에 approval 없을 때만) — delete_record 등 기존 게이트 보존.
    legacy = _APPROVAL_ACTIONS.get((server, tool))
    return legacy is not None, "admin", legacy or f"mcp.{server}.{tool}"


def _apply_approval_override(
    required: bool, approver: str, server: str, tool: str, tool_policy: dict | None
) -> tuple[bool, str]:
    """에이전트 오버라이드(스펙 177 P2) — tool_policy["mcp:{server}/{tool}"].approval의
    required/approver로 덮음(있는 키만). 강화·완화·approver 변경 모두 여기서 — 완화 권한 게이트는
    저장 시점(agents CRUD)에서 강제, 리졸버는 순수 해석만."""
    if isinstance(tool_policy, dict):
        entry = tool_policy.get(f"mcp:{server}/{tool}")
        ov = entry.get("approval") if isinstance(entry, dict) else None
        if isinstance(ov, dict):
            if "required" in ov:
                required = bool(ov["required"])
            if ov.get("approver"):
                approver = ov["approver"]
    return required, approver


def resolve_tool_approval(
    server: str,
    tool: str,
    tools_meta: dict | None = None,
    tool_policy: dict | None = None,
) -> dict | None:
    """도구 승인 정책 리졸버(스펙 177) — 승인이 필요하면 `{"permission", "approver"}`, 아니면 None.

    **단일 진실원**: 그래프-tools 경로(`_wrap_mcp_tool`)와 브로커 경로
    (`broker.McpProvider.approval_for`)가 이 함수 하나를 공유한다(드리프트 0). 우선순위:
      1. **도구 기본**(P1) = `_base_approval` — tools_meta, 없으면 레거시 폴백.
      2. **에이전트 오버라이드**(P2) = `_apply_approval_override` — tool_policy로 덮음.
    approver는 승인 인가에 쓰인다(`approvals._may_resolve`): admin=관리자만, self=요청 소유자 본인.
    permission 문자열은 표시·감사·레거시 하위호환용(인가는 approver 필드로 — 세그먼트 이스케이프 무관).
    """
    required, approver, permission = _base_approval(server, tool, tools_meta)
    required, approver = _apply_approval_override(required, approver, server, tool, tool_policy)
    if not required:
        return None
    return {
        "permission": permission,
        "approver": approver if approver in ("admin", "self") else "admin",
    }


# 실 도구 호출 전체 deadline(초). per-read 타임아웃은 전체 데드라인이 아니므로(learning 046)
# asyncio.timeout으로 호출 전체를 감싼다 — 느린/멈춘 서버가 에이전트를 무한 대기시키지 않게.
_TOOL_TIMEOUT_S = 30


def _wrap_mcp_tool(
    server: str, rt: BaseTool, calls_sink: list[dict], approval: dict | None
) -> StructuredTool:
    """실 MCP 도구(rt)를 트레이스·HIL 게이트·graceful 래퍼로 감싼다.

    rt.args_schema(JSON 스키마 dict)를 그대로 보존해 LLM이 원 도구 시그니처대로 호출하게 한다.
    `approval`(호출부 `resolve_tool_approval`가 해석, 스펙 177 = `{permission, approver}` 또는 None)이
    non-None인 도구는 **rt.ainvoke(부수효과) 이전에 interrupt()** 로 그래프를 멈춰 승인을 받는다(스펙 041
    불변식, 실 도구 위에서 재성립). approver(admin/self)는 interrupt 페이로드로 실려 Approval에 스탬프됨
    → `approvals._may_resolve` 인가에 쓰인다. 도구 실행 실패(서버 다운·프로토콜·타임아웃)는 잡아 graceful
    문자열 + calls_sink status="error"로 — 에이전트 크래시 금지.
    """
    permission = approval["permission"] if approval else None
    approver = (approval.get("approver") or "admin") if approval else "admin"

    # 도구 실패를 이 래퍼의 단일 except로 모은다(스펙 320). langchain-mcp-adapters는 MCP
    # `isError=True`를 ToolException(_MCPToolExecutionError)으로 만든 뒤 tool.handle_tool_error로
    # **삼켜 정상 문자열**로 돌려준다("Error executing tool …") → status=ok로 오기록돼 사유가 사라진다.
    # handle_tool_error를 끄면 그 예외가 아래 except로 전파돼 status=error + 실제 사유(str(exc))를
    # 붙잡는다(전송/프로토콜 실패는 원래 ToolException이 아니라 이미 전파 — 한 경로로 수렴).
    with contextlib.suppress(Exception):  # rt 타입이 예상 밖이면 조용히 넘어감(무회귀)
        rt.handle_tool_error = False

    async def _execute(kwargs: dict, t0: float, sink: list[dict]) -> str:
        # 실 부수효과: 실제 MCP 서버 도구를 호출한다. 승인됐거나 비위험 도구일 때만 도달.
        reason: str | None = None  # 실패 사유(스펙 320) — 성공 시 None
        try:
            async with asyncio.timeout(_TOOL_TIMEOUT_S):
                raw = await rt.ainvoke(kwargs)
            text = _content_text(raw)
            status = "ok"
        except Exception as exc:
            # 예외 타입에서 앞 밑줄 제거 — 어댑터 내부 클래스명(_MCPToolExecutionError)이 그대로
            # UI에 새어 지저분해지지 않게(정돈=신뢰). 밑줄 없는 표준 예외명은 그대로 유지.
            etype = type(exc).__name__.lstrip("_")
            status = "error"
            # 실제 사유(str(exc))를 붙잡아 인스펙터에 표면화(스펙 320) — 예외 타입만으론 "왜"를 못 본다.
            # 마스킹+캡 백스톱 통과(사유가 새 노출 표면 — 토큰/입력값 누출 차단, learning 092).
            reason = _sanitize_preview(f"{etype}: {exc}", _ERR_CAP)
            # 모델-facing 텍스트에도 사유를 싣는다(스펙 320): handle_tool_error를 끄며 어댑터의 상세
            # 오류 문자열이 사라지므로, 트레이스뿐 아니라 에이전트도 "왜 실패했는지"를 보고 적응·재시도할
            # 수 있게(toolbox.py agent-call 실패가 str(exc)를 싣는 선례와 동형). reason은 이미 마스킹+캡됨.
            text = f"도구 실행 실패({server}.{rt.name}): {reason}"
        sink.append(
            {
                "server": server,
                "tool": rt.name,
                "status": status,
                "ms": int((time.perf_counter() - t0) * 1000) + 1,
                "args": _redact_args(
                    kwargs
                ),  # 스펙 087: 민감 키 마스킹 전 적재(형제 표면 누출 차단)
                # 스펙 211: 직접 MCP 결과도 브로커/RAG와 같은 정화 경로(_sanitize_preview=비밀 마스킹+캡).
                # 사용=공용 전환으로 타인이 크레덴셜 MCP를 배선할 수 있어(사용자 결정: 전부 공용), 결과에
                # 섞인 토큰/비밀이 trace·응답으로 새지 않게 마스킹(codex 211 P2). 구 _cap은 마스킹 없었음.
                "result": _sanitize_preview(text, _RESULT_CAP),
                **({"error": reason} if reason else {}),  # 실패 사유(스펙 320) — 성공 기록엔 미포함
            }
        )
        return text

    async def _run(config: RunnableConfig = None, **kwargs: Any) -> str:
        t0 = time.perf_counter()
        sink = _sink_from(config, calls_sink)
        if permission is None:
            return await _execute(kwargs, t0, sink)
        # 위험 도구: 실 부수효과 이전에 일시정지. interrupt()는 첫 호출 시 그래프를 멈추고,
        # admin이 Command(resume={"decision":...})로 재개하면 그 값을 반환한다(도구는 처음부터
        # 재실행되지만 interrupt 이전엔 부수효과가 없어 정확히 1회만 ainvoke — 스펙 041 probe로 검증).
        decision = interrupt(
            {
                "permission": permission,
                "approver": approver,  # 스펙 177 P2 — Approval에 스탬프돼 _may_resolve 인가에 쓰임
                "server": server,
                "tool": rt.name,
                "action": f"{server}.{rt.name}",
                "args": _redact_args(
                    kwargs
                ),  # 스펙 087: Approval.args(DB 영속)·ApprovalsView로 새기 전 마스킹
                "summary": f"{server}.{rt.name} 실행 — {'본인' if approver == 'self' else '관리자'} 승인 필요",
            }
        )
        approved = isinstance(decision, dict) and decision.get("decision") == "approve"
        if not approved:
            # 거부: 부수효과 0(ainvoke·sink 미emit) — 에이전트는 이 사실로 마무리.
            return "거부됨 — 관리자가 실행을 승인하지 않았습니다."
        return await _execute(kwargs, t0, sink)

    desc = rt.description or f"{server} 서버의 {rt.name} 도구."
    if permission is not None:
        desc += " ⚠ 위험 작업: 호출 시 관리자 승인 전까지 일시정지됩니다."
    return StructuredTool.from_function(
        coroutine=_run,
        name=_safe_name(server, rt.name),
        description=desc,
        args_schema=rt.args_schema,
    )


def mcp_connection(server: dict) -> dict | None:
    """서버 dict(`{name,url,transport,auth_token}`)를 `MultiServerMCPClient` 연결 dict로 변환.

    미지원 transport(stdio 등)나 SSRF 차단 URL이면 None(호출부가 그 서버를 스킵). `build_mcp_tools`(그래프
    preload)와 능력 브로커 `McpProvider`(동적 discover→invoke, 스펙 101)가 **이 한 함수를 공유**해
    transport·Bearer·리다이렉트 하드닝(`mcp_http_client_factory`) 정책이 한 곳에서만 산다(드리프트 0).
    호출 전 `net_guard.refresh_allowed_hosts()`는 호출부 책임(루프당 1회 — DB round-trip 중복 방지)."""
    from . import net_guard

    if (server.get("transport") or "").lower() not in ("http", "streamable_http"):
        return None  # stdio 등 미지원 transport
    url = server.get("url") or ""
    # 스펙 360: 우리 자체 served MCP(플랫폼이 자기 자신에 붙는 127.0.0.1 서빙 엔드포인트)는 SSRF
    # 판정 대상이 아니다 — 목적지가 사용자 입력이 아니라 served_url(name)로 플랫폼이 정한 고정값이라
    # SSRF가 아니다. 데이터 리셋으로 allowed_hosts에서 127.0.0.1이 빠져도 자체 served MCP는 동작해야
    # 한다. 예외는 의도 신호(레지스트리 이름 + served_url 정확 일치)라 사용자가 임의 url로 우회 못 함.
    from .served_mcp import is_own_served_url

    if not is_own_served_url(server.get("name"), url):
        try:
            net_guard.guard_url(url)
        except net_guard.SsrfBlockedError:
            return None  # SSRF 차단 서버는 연결 자체를 안 함(부수효과 0)
    headers: dict[str, str] = {}
    token = server.get("auth_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return {
        "transport": "streamable_http",
        "url": url,
        "headers": headers or None,
        # 리다이렉트-SSRF 차단(적대 리뷰 H1): 기본 클라이언트는 3xx를 따라가 가드를 우회하고 토큰을
        # 재전송한다 → follow_redirects=False 팩토리로 fail-closed(a2a_client와 동일 정책).
        "httpx_client_factory": net_guard.mcp_http_client_factory,
    }


def selected_for_server(server: str, selected: list[str] | None) -> set[str] | None:
    """이 서버에 대한 도구 노출 필터(스펙 276) — None=전체 노출(폴백), set=그 런타임명만.

    selected 항목은 런타임명(`server__tool`, _safe_name 산출). 서버명은 NAME_RULE(영소문자·숫자·대시,
    밑줄 금지)이라 `server__` 접두 분리가 모호하지 않다(272 불변식 공유). **이 서버 항목이 하나도
    없으면 None(전체)** — 이 폴백 하나가 세 무회귀를 담당: ①구저장(tools 빈 목록)=기존과 동일,
    ②오버라이드로 서버 통째 추가, ③카탈로그에 도구 목록이 없는 서버의 보존."""
    if not selected:
        return None
    prefix = f"{server}__"
    mine = {s for s in selected if isinstance(s, str) and s.startswith(prefix)}
    return mine or None


# ── MCP 도구 사양 캐시(스펙 371 D1) ─────────────────────────────────────────────
# get_tools(HTTP 디스커버리) 결과(raw 도구)를 (서버명, 블록 버전, auth 지문) 키로 캐시.
# 369 불변성: 버전 payload가 append-only 불변 → TTL 무한·무효화 로직 불요(새 버전=새 키,
# auth 로테이션=새 지문). per-turn 래핑(_wrap_mcp_tool: calls_sink·승인)은 캐시하지 않고 매턴
# 재수행 — 동시 턴 트레이스 교차 오염이 구조적으로 불가. 프로세스-로컬(단일 uvicorn 전제).
_TOOL_SPEC_CACHE: "dict[tuple, list]" = {}
_TOOL_SPEC_CACHE_MAX = 256
_TOOL_SPEC_LOCK = asyncio.Lock()  # miss 직렬화(같은 서버 동시 miss의 중복 디스커버리 방지)
mcp_tool_cache_stats = {"hits": 0, "misses": 0}  # 검증용(스펙 371 C2)


def _tool_spec_cache_key(server: dict) -> tuple:
    auth_fp = hashlib.sha256((server.get("auth_token") or "").encode()).hexdigest()[:8]
    return (server["name"], server.get("version") or 0, auth_fp)


async def _raw_tools_cached(server: dict, conn: dict | None) -> list | None:
    """서버의 raw 도구 목록 — 캐시 적중이면 아웃바운드 0, miss면 실연결·디스커버리 후 적재."""
    key = _tool_spec_cache_key(server)
    cached = _TOOL_SPEC_CACHE.get(key)
    if cached is not None:
        mcp_tool_cache_stats["hits"] += 1
        return cached
    if conn is None:
        return None  # miss인데 연결 준비 실패(SSRF 차단 등) — 호출부가 스킵
    async with _TOOL_SPEC_LOCK:
        cached = _TOOL_SPEC_CACHE.get(key)  # double-check(락 대기 중 채워졌으면 재사용)
        if cached is not None:
            mcp_tool_cache_stats["hits"] += 1
            return cached
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({server["name"]: conn})
        raw = await client.get_tools(server_name=server["name"])
        mcp_tool_cache_stats["misses"] += 1
        if len(_TOOL_SPEC_CACHE) >= _TOOL_SPEC_CACHE_MAX:
            _TOOL_SPEC_CACHE.pop(next(iter(_TOOL_SPEC_CACHE)))  # 최고령 축출(삽입순)
        _TOOL_SPEC_CACHE[key] = raw
        log.info("MCP 도구 사양 캐시 적재: %s v%s (%d개)", key[0], key[1], len(raw))
        return raw


async def _prepare_connections(servers: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """연결 준비(스펙 397 분해) — 반환 (connections, meta). 캐시 적중 예정 서버는 연결 불요.

    pending(캐시 miss) 계산 후 **가드(mcp_connection)보다 먼저** allowed_hosts 갱신 — 콜드 스냅샷
    위에서 가드를 돌리면 정당한 서버가 조용히 잘린다(스펙 371 실측: 순서 뒤집혔을 때 calc-tools
    매턴 탈락). miss 있을 때만 refresh(DB round-trip 절약)."""
    connections: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    pending = [s for s in servers if _tool_spec_cache_key(s) not in _TOOL_SPEC_CACHE]
    if pending:
        from . import net_guard

        await net_guard.refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064)
    for server in servers:
        if server not in pending:
            meta[server["name"]] = server  # 캐시 적중 예정 — 연결 준비 불요(스펙 371 D1)
            continue
        conn = mcp_connection(
            server
        )  # transport 검사·SSRF 가드 공유 헬퍼(브로커와 드리프트 0, 스펙 101)
        if conn is None:
            continue  # 미지원 transport 또는 SSRF 차단 → 그 서버만 스킵
        connections[server["name"]] = conn
        meta[server["name"]] = server
    return connections, meta


def _tools_from_raw(
    name: str,
    s: dict,
    raw_tools: list,
    calls_sink: list[dict],
    tool_policy: dict | None,
    selected_tools: list[str] | None,
) -> list[StructuredTool]:
    """서버 하나의 raw 도구를 필터(enabled·selected)·승인 해석·래핑해 반환(스펙 397 분해)."""
    enabled = set(s.get("enabled_tools") or [])
    sel = selected_for_server(name, selected_tools)  # 도구 단위 배선 필터(스펙 276)
    tools: list[StructuredTool] = []
    for rt in raw_tools:
        if enabled and rt.name not in enabled:
            continue  # enabled_tools 밖 도구는 노출 안 함(서버측 강제)
        if sel is not None and _safe_name(name, rt.name) not in sel:
            continue  # 에이전트가 고른 도구 밖 — 노출 안 함(스펙 276 도구 단위 배선)
        # 스펙 177 단일 리졸버 — 도구 기본(tools_meta) ◁덮음◁ 에이전트 오버라이드(tool_policy).
        appr = resolve_tool_approval(name, rt.name, s.get("tools_meta"), tool_policy)
        tools.append(_wrap_mcp_tool(name, rt, calls_sink, appr))
    return tools


async def build_mcp_tools(
    servers: list[dict],
    calls_sink: list[dict],
    tool_policy: dict | None = None,
    selected_tools: list[str] | None = None,
) -> list[StructuredTool]:
    """등록 MCP 서버에 **실제로 연결**(MultiServerMCPClient)해 활성 도구를 LangChain 툴로 만든다.

    `servers`: `_load_context`가 해석한 dict 리스트
      `{name, url, transport, enabled_tools, auth_token(복호화|None)}`.
    HTTP/streamable만 연결한다(stdio는 스펙 054 §7에서 유예). 각 URL은 연결 이전에 net_guard(스펙
    042)로 SSRF 검사 — 사설/루프백 IP는 차단하되 DB allowlist(스펙 064 `allowed_hosts`)로 dev
    mock(127.0.0.1)을 통과시킨다(루프 전 refresh로 무재시작 반영). 서버 하나가 다운/차단/프로토콜
    오류여도 그 서버만 건너뛰고 나머지는 살린다(부분 실패
    격리 — 에이전트는 계속 실행). 각 도구는 `_wrap_mcp_tool`로 트레이스·HIL·graceful 래핑된다.
    """
    connections, meta = await _prepare_connections(servers)
    if not meta:
        return []
    tools: list[StructuredTool] = []
    for name, s in meta.items():
        try:
            raw_tools = await _raw_tools_cached(s, connections.get(name))
        except Exception:
            continue
        if raw_tools is None:
            continue
        tools.extend(_tools_from_raw(name, s, raw_tools, calls_sink, tool_policy, selected_tools))
    return tools


# NOTE(스펙 051): 채팅 인-챗 자가기록 도구(`save_agent_knowledge` /
# build_agent_memory_tool)는 제거됐다. LLM이 도구 설명("유저 개인정보 금지")을 어기고 유저
# 개인사실을 agent_id(교차사용자) 스코프에 써서 누출시켰다(learning 031 "도구 프롬프트 ≠ 격리").
# agent_id 메모리는 이제 **어드민 저작 전용**(agents.py CRUD) — 인간 게이트만 둔다. 회상은 유지.
