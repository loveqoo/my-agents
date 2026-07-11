"""kind=mcp provider(스펙 101 Phase 2-a) — `McpServer`의 enabled_tools 툴 단위 능력.

`_adapt_args`는 `_tool_input_schema`와 같은 모듈(드리프트 0 짝 — generic 인자 적응이
툴 스키마 정규화에 정합).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from agent.runtime import Capability, InvokeResult

from ...models import McpServer
from ..common import CAP_KIND_MCP, _first_line, _kind_of, _parse_mcp, _rt

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _tool_input_schema(tool: BaseTool) -> dict | None:
    """MCP 툴의 inputSchema를 JSON 스키마 dict로 정규화(pydantic 모델이면 model_json_schema)."""
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, dict):
        return schema
    if schema is not None and hasattr(schema, "model_json_schema"):
        try:
            return schema.model_json_schema()
        except Exception:
            return None
    return None


def _pick_value(args: dict) -> object:
    """generic 인자에서 실어 보낼 값 하나 — text/query/input 우선, 없으면 첫 값."""
    return (
        args.get("text") or args.get("query") or args.get("input") or next(iter(args.values()), "")
    )


def _target_param(props: dict) -> str | None:
    """값을 실을 대상 파라미터 — 단일 파라미터 툴이면 그것, 아니면 알려진 이름 중 첫 매칭(없으면 None)."""
    if len(props) == 1:
        return next(iter(props))
    for cand in ("text", "query", "input", "message", "q"):
        if cand in props:
            return cand
    return None


def _adapt_args(tool: BaseTool, args: dict) -> dict:
    """generic 위임 인자(`{"text": query}`, orchestrate가 kind-무관하게 넘김)를 **툴의 실제 파라미터**로
    적응한다. flow는 A2A 모양(`text`)으로 부르지만 MCP 툴은 자기 시그니처(예 web_search(query),
    delete_record(record_id))를 가진다 — flow 코드 변경 없이(스펙 101 §3.4) 여기서 매핑한다.
    스키마 키가 이미 맞으면 통과, 아니면 단일 파라미터/알려진 이름으로 값 하나를 실어 보낸다."""
    if not isinstance(args, dict):
        args = {"text": str(args)}
    props = (_tool_input_schema(tool) or {}).get("properties") or {}
    if not props or set(args) <= set(props):
        return args  # 스키마 없음(무검증 통과) 또는 이미 적합
    target = _target_param(props)
    if target is None:
        return args  # 매핑 불가 → 원본(툴이 graceful 실패로 처리)
    return {target: _pick_value(args)}


def _tool_allowed(name: str, enabled: set, allowset: set | None) -> bool:
    """candidates·load 공유 필터 — enabled_tools(서버측 강제)와 allowlist(특정 툴만) 둘 다 통과하는가."""
    if enabled and name not in enabled:
        return False  # enabled_tools 밖(서버측 강제)
    # allowlist가 특정 툴만 허용하면 그 외 미노출(None=서버 전체 허용).
    return allowset is None or name in allowset


class _McpBacking:
    """McpProvider.load가 돌려주는 backing — 서버명·툴명 + **연결로 실제 가져온 BaseTool**.
    describe(스키마)·invoke(ainvoke)·node_label이 이 tool을 그대로 쓴다."""

    __slots__ = ("server", "tool", "tool_name", "tools_meta")

    def __init__(
        self, server: str, tool_name: str, tool: BaseTool, tools_meta: dict | None = None
    ) -> None:
        self.server = server
        self.tool_name = tool_name
        self.tool = tool
        self.tools_meta = tools_meta  # 도구 승인 정책 리졸버용(스펙 177)


class McpProvider:
    """kind=mcp — `McpServer`의 **enabled_tools 툴 단위**를 능력으로. 전송은 `runtime.mcp_connection`
    (build_mcp_tools와 공유) + `MultiServerMCPClient` 재사용. MCP는 이름만 DB에 저장하므로 hook·스키마·
    invoke는 서버에 실제로 붙어 얻는다(catalog 작아 one-shot 연결 허용, 설계결정 10)."""

    kind = CAP_KIND_MCP

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _mcp_allow(self, allow: set[str]) -> dict:
        """allowlist의 mcp 항목 → `{server: set(tools) | None}`(None=서버 전체 허용, 그 서버 enabled_tools 전부)."""
        spec: dict[str, set | None] = {}
        for it in allow:
            if _kind_of(it) != CAP_KIND_MCP:
                continue
            server, tool = _parse_mcp(it)
            if tool is None:
                spec[server] = None  # 서버 전체(그 툴을 덮음)
            elif spec.get(server, "∅") is None:
                continue  # 이미 서버 전체 허용 → 개별 툴 항목은 무의미
            else:
                bucket = spec.setdefault(server, set())
                assert bucket is not None  # 위 elif가 서버 전체(None) 항목을 걸러 이 분기 미도달
                bucket.add(tool)
        return spec

    async def _server_dicts(self, server_names: set[str]) -> list[dict]:
        """McpServer 행 → build_mcp_tools 계약 dict(name/url/transport/enabled_tools/auth_token).
        auth는 chat._load_context와 동일 규칙으로 복호화(마스킹/빈값→None → 헤더 생략, drift 0)."""
        from ... import crypto

        async with self._session_factory() as db:
            rows = (
                (await db.execute(select(McpServer).where(McpServer.name.in_(server_names))))
                .scalars()
                .all()
            )
        out: list[dict] = []
        for row in rows:
            token = None if crypto.is_masked(row.auth) else crypto.decrypt(row.auth)
            out.append(
                {
                    "name": row.name,
                    "url": row.url or row.endpoint or "",
                    "transport": row.transport or "http",
                    "enabled_tools": list(row.enabled_tools or []),
                    "auth_token": token,
                    "tools_meta": row.tools_meta or {},  # 도구 승인 정책 리졸버용(스펙 177)
                }
            )
        return out

    async def _get_tools(self, server_name: str, conn: dict) -> list:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # 지연 임포트

        client = MultiServerMCPClient({server_name: conn})
        return await client.get_tools(server_name=server_name)

    async def _tools_for_server(self, server_name: str, conn: dict) -> list | None:
        """서버 툴 목록 로드(연결/프로토콜 실패 → None) — candidates·load 공유."""
        try:
            return await self._get_tools(server_name, conn)
        except Exception:
            return None

    async def candidates(self, allow: set[str]) -> list[Capability]:
        spec = self._mcp_allow(allow)
        if not spec:
            return []  # mcp-kind 항목 없음 → DB/네트워크 미접촉
        from ... import net_guard

        await net_guard.refresh_allowed_hosts()  # DB allowlist 무재시작 반영(127.0.0.1 mock 통과)
        caps: list[Capability] = []
        for server in await self._server_dicts(set(spec)):
            conn = _rt().mcp_connection(server)
            if conn is None:
                continue  # 미지원 transport/SSRF 차단 → 그 서버 스킵
            enabled = set(server.get("enabled_tools") or [])
            allowset = spec.get(server["name"])  # None=서버 전체
            tools = await self._tools_for_server(server["name"], conn)
            if tools is None:
                continue
            caps.extend(
                Capability(
                    id=f"{CAP_KIND_MCP}:{server['name']}/{t.name}",
                    kind=CAP_KIND_MCP,
                    name=t.name,
                    hook=_first_line(getattr(t, "description", "") or "", t.name),
                )
                for t in tools
                if _tool_allowed(t.name, enabled, allowset)
            )
        return caps

    async def load(self, cap_id: str) -> _McpBacking | None:
        server, tool = _parse_mcp(cap_id)
        if tool is None:
            return None  # `mcp:server`(툴 미지정)는 호출 불가 대상 → 존재 비노출
        from ... import net_guard

        await net_guard.refresh_allowed_hosts()
        servers = await self._server_dicts({server})
        if not servers:
            return None
        s = servers[0]
        conn = _rt().mcp_connection(s)
        if conn is None:
            return None
        enabled = set(s.get("enabled_tools") or [])
        if not _tool_allowed(tool, enabled, None):
            return None  # enabled 밖 → 존재 비노출
        tools = await self._tools_for_server(server, conn)
        if tools is None:
            return None
        match = next((t for t in tools if t.name == tool), None)
        if match is None:
            return None
        return _McpBacking(server, tool, match, s.get("tools_meta"))

    def describe(self, row: _McpBacking) -> Capability:
        return Capability(
            id=f"{CAP_KIND_MCP}:{row.server}/{row.tool_name}",
            kind=CAP_KIND_MCP,
            name=row.tool_name,
            hook=_first_line(getattr(row.tool, "description", "") or "", row.tool_name),
            input_schema=_tool_input_schema(row.tool),  # A2A의 고정 {text}와 달리 툴별 실제 스키마
        )

    async def invoke(self, row: _McpBacking, args: dict) -> InvokeResult:
        import asyncio

        from ...runtime import _TOOL_TIMEOUT_S, _content_text

        cap_id = f"{CAP_KIND_MCP}:{row.server}/{row.tool_name}"
        try:
            async with asyncio.timeout(_TOOL_TIMEOUT_S):
                raw = await row.tool.ainvoke(_adapt_args(row.tool, args))
            text = _content_text(raw)  # content-block 리스트 → str 정규화(092 재사용)
            err = None
        except Exception as exc:
            text = ""
            err = f"MCP 도구 실행 실패({row.server}/{row.tool_name}): {type(exc).__name__}"
        return InvokeResult(
            text=text,
            trust="untrusted",
            error=err,
            raw={"cap_id": cap_id, "kind": CAP_KIND_MCP},
        )

    def node_label(self, row: _McpBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MCP}:{row.server}/{row.tool_name}"

    def approval_for(
        self, row: _McpBacking, cap_id: str, args: dict, tool_policy: dict | None = None
    ) -> dict | None:
        """MCP 승인 정책 = 그래프-tools 경로와 **동일 리졸버**(`resolve_tool_approval`, 스펙 177) 공유
        (드리프트 0 — 관리자가 tools_meta로 설정한 정책이 두 경로 일관 적용). 마스킹은 `_redact_args`
        재사용. 걸리지 않는 툴은 None(즉시 실행)."""
        from ...runtime import _redact_args, resolve_tool_approval

        server, tool = _parse_mcp(cap_id)
        assert tool is not None  # load()가 툴 미지정 cap을 None으로 걸러 approval_for 미도달
        appr = resolve_tool_approval(server, tool, getattr(row, "tools_meta", None), tool_policy)
        if appr is None:
            return None
        approver = appr.get("approver", "admin")
        return {
            "permission": appr["permission"],
            "approver": approver,  # 스펙 177 P2 — Approval 스탬프 → _may_resolve 인가
            "server": server,
            "tool": tool,
            "action": f"{server}.{tool}",
            "args": _redact_args(args if isinstance(args, dict) else {"text": args}),
            "summary": f"{server}.{tool} 실행 — {'본인' if approver == 'self' else '관리자'} 승인 필요",
        }
