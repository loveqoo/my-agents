"""내부(커스텀) MCP를 외부로 서빙 (스펙 156, 실사용 #4).

우리는 외부 MCP를 **등록해 클라이언트로 붙어 쓴다**(runtime.build_mcp_tools + MultiServerMCPClient).
이 파일은 그 반대편 — 우리가 코드로 정의한 도구를 **진짜 MCP 엔드포인트로 서빙**해 외부 MCP
클라이언트/에이전트가 붙게 한다. "langgraph에서 mcp 만들어 외부 공개"의 실체:
LangChain 도구(@tool) → `to_fastmcp` → `FastMCP(..., tools=[...])` → streamable-HTTP(mock_mcp 동형).

에이전트 모델 미러: 에이전트는 A2A로 서빙(154), MCP는 여기서 서빙. external MCP는 **서빙 불가**
(재공개 봉인, 스펙 152) — 서빙 대상은 우리가 호스팅하는 source="custom" MCP뿐이며, 그중에서도
이 레지스트리에 실 정의가 있는 이름만 서빙된다(등록 행만 있고 정의 없는 이름은 서빙 안 됨).

게이트는 main.py의 마운트 가드가 요청마다 DB로 확인한다(published + source=custom + 레지스트리 존재).
정의만 있고 미공개면 404(노출 안 된 것 누출 금지, a2a_server 동형).
"""

from langchain_core.tools import tool
from langchain_mcp_adapters.tools import to_fastmcp
from mcp.server.fastmcp import FastMCP

# 서빙 대상 유래(스펙 156) — 우리가 코드로 정의·호스팅하는 MCP만. external은 봉인(152), local은
# 외부/self-host 등록분이라 서빙 대상 아님(우리 정의가 아님).
SERVABLE_SOURCE = "custom"

# 서빙 경로 프리픽스(mock_remote/_remote 관례) — main.py 마운트와 단일 소스.
SERVED_MCP_PREFIX = "/_served/mcp"


# ---- 커스텀 도구(LangChain @tool → to_fastmcp) ----
@tool
def add(a: int, b: int) -> int:
    """두 정수를 더한다(결정적)."""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """두 정수를 곱한다(결정적)."""
    return a * b


@tool
def echo(text: str) -> str:
    """입력 텍스트를 그대로 돌려준다(연결·왕복 확인용)."""
    return text


# 서빙 MCP 정의(단일 출처) — 이름 → (도구 리스트, 메타). 시드 카탈로그·서빙 앱이 이걸 공유(드리프트 0).
_DEFS: dict[str, list] = {
    "calc-tools": [add, multiply, echo],
}

# 시드 카탈로그가 쓰는 도구 이름/메타(mock_mcp 패턴 — 평행 리터럴 드리프트 방지).
SERVED_MCP_TOOLS: dict[str, list[str]] = {name: [t.name for t in tools] for name, tools in _DEFS.items()}
SERVED_MCP_TOOLS_META: dict[str, dict] = {
    name: {
        t.name: {
            "description": (t.description or "").strip(),
            # t.args = {argname: {title,type,...}} — 서빙 도구가 요구하는 인자는 전부 필수(간단 도구).
            "params": [
                {"name": pn, "type": (pinfo.get("type") or "string"), "required": True}
                for pn, pinfo in (t.args or {}).items()
            ],
        }
        for t in tools
    }
    for name, tools in _DEFS.items()
}


def _build(name: str, tools: list) -> FastMCP:
    """LangChain 도구를 FastMCP로 서빙 가능한 앱으로 — to_fastmcp 변환 후 constructor tools=로 등록.
    stateless_http=True: 매 요청 독립(영속 세션 매니저 불필요, mock_mcp 동형)."""
    fastmcp_tools = [to_fastmcp(t) for t in tools]
    return FastMCP(name, streamable_http_path="/", stateless_http=True, tools=fastmcp_tools)


# 안전 불변식(스펙 156, codex Low 경계): 서빙 라우트는 전역 인증 밖(mock_mcp처럼) — published custom
# MCP는 **무인증 공개 API**다. 그래서 서빙 도구는 반드시 **부수효과 없는(read-only/순수) 도구**여야
# 한다(HIL 승인 대상 delete_record류를 서빙하면 무인증 실행면이 된다). 새 도구를 서빙에 추가하려면
# 이 allowlist에 명시적으로 등록해야 부팅이 통과 — "무심코 위험 도구 서빙"을 부팅에서 강제 차단한다.
_SIDE_EFFECT_FREE_TOOLS = {"add", "multiply", "echo"}
for _n, _ts in _DEFS.items():
    _unsafe = {t.name for t in _ts} - _SIDE_EFFECT_FREE_TOOLS
    if _unsafe:
        raise RuntimeError(
            f"서빙 MCP '{_n}'에 부수효과 미검증 도구 {sorted(_unsafe)} — 무인증 서빙 대상은 "
            "_SIDE_EFFECT_FREE_TOOLS에 명시적으로 등록된 순수 도구만 허용됩니다(스펙 156 안전 불변식)."
        )

# 이름 → FastMCP 서버(부팅 시 1회 구성). main.py가 각 이름을 `/_served/mcp/{name}`에 가드와 함께 마운트.
SERVED_MCPS: dict[str, FastMCP] = {name: _build(name, tools) for name, tools in _DEFS.items()}


def served_url(name: str, base: str = "http://127.0.0.1:8000") -> str:
    """서빙 URL(끝 슬래시 필수 — mount+path 조합이 trailing-slash 기대, mock_mcp 동형)."""
    return f"{base.rstrip('/')}{SERVED_MCP_PREFIX}/{name}/"


async def _is_served(name: str) -> bool:
    """서빙 게이트(스펙 156) — DB로 요청마다 확인. published + source=custom + 레지스트리 존재.
    미공개/미등록/유래 불일치면 False → 404(노출 안 된 것의 존재·구성 누출 금지, a2a_server 동형).
    external은 애초에 여기 못 옴(source=custom만 통과) — 재공개 봉인(152) 이중 게이트."""
    from sqlalchemy import select

    from .db import SessionLocal
    from .models import McpServer

    if name not in SERVED_MCPS:
        return False
    async with SessionLocal() as db:
        row = (await db.execute(select(McpServer).where(McpServer.name == name))).scalar_one_or_none()
    return row is not None and row.source == SERVABLE_SOURCE and bool(row.published)


def guarded_app(name: str, inner):
    """`inner`(FastMCP streamable_http_app)를 공개 게이트로 감싼 ASGI 앱. http 요청만 게이트하고
    lifespan 등은 통과(세션 매니저는 main lifespan이 직접 run — 마운트 lifespan 자동실행 안 됨)."""

    async def app(scope, receive, send):
        if scope.get("type") != "http":
            await inner(scope, receive, send)
            return
        if not await _is_served(name):
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"detail":"served mcp not found"}',
            })
            return
        await inner(scope, receive, send)

    return app
