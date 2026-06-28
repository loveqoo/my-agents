"""self-host 실 mock MCP 서버 (스펙 054 — mock_remote/spec 024 패턴의 MCP 판).

라이브 외부 MCP 서버 없이도 **실 MCP 프로토콜 연결**을 끝까지 검증·시연하기 위해, MCP SDK의
`FastMCP`로 결정적 도구를 노출하는 진짜 streamable-HTTP MCP 서버를 우리 API에 self-host한다
(`/_remote/mcp/`). 이 서버를 가리키도록 `McpServer` 행을 등록하면 `runtime.build_mcp_tools`가
`MultiServerMCPClient`로 실제로 붙어 도구를 호출한다 — 반환값은 하드코딩 문자열(_CANNED 폐기)이
아니라 **이 서버가 실제로 계산한 값**이다(learning 039: drop-in은 두 번째 구현으로 측정).

마운트: main.py가 `streamable_http_app()`를 `/_remote/mcp`로 mount하고, FastMCP의 세션 매니저
lifespan(`session_manager.run()`)을 앱 lifespan에서 연다(마운트된 서브앱 lifespan은 자동 실행되지
않으므로 부모가 직접 진입). stateless_http=True — 매 요청 독립 처리(영속 세션 매니저 불필요).

지배 스펙: docs/spec/054-mcp-real-runtime-http.md, docs/spec/024-mock-llm-registry-model.md
"""

from mcp.server.fastmcp import FastMCP

# 등록·HIL이 참조하는 정식 이름/URL의 단일 소스 — seed와 runtime._APPROVAL_ACTIONS가 이걸 쓴다(drift 방지).
MOCK_MCP_SERVER_NAME = "local-tools"
# self-host MCP 엔드포인트(루프백). 끝의 슬래시 필수 — mount(/_remote/mcp)+path(/) 조합이 trailing-slash를 기대.
MOCK_MCP_URL = "http://127.0.0.1:8000/_remote/mcp/"
# 이 서버가 노출하는 도구 이름 — seed/reconcile의 카탈로그 enabled_tools 기본값 단일 소스(drift 방지).
# 권위 있는 출처는 라이브 get_tools지만, 시드 기본값은 이 상수로 통일해 평행 리터럴 드리프트를 막는다.
MOCK_MCP_TOOLS = ["web_search", "echo", "delete_record"]

mcp = FastMCP("my-agents-local-tools", streamable_http_path="/", stateless_http=True)


@mcp.tool()
def web_search(query: str) -> str:
    """웹을 검색해 관련 결과 요약을 돌려준다(개발용 결정적 mock). 같은 query면 같은 결과."""
    q = (query or "").strip()
    return (
        f"[local-tools:web_search] '{q}'에 대한 검색결과 3건(결정적 mock). "
        "1) 개요 문서 2) 관련 토론 3) 참고 링크 — 라이브 검색 없이 MCP 서버가 실제로 응답했습니다."
    )


@mcp.tool()
def echo(text: str) -> str:
    """입력 텍스트를 그대로 돌려준다(연결·왕복 확인용)."""
    return text


@mcp.tool()
def delete_record(record_id: str) -> str:
    """레코드를 삭제한다(위험 작업 — HIL 승인 게이트 대상, 스펙 041). 부수효과를 흉내내는 mock."""
    rid = (record_id or "").strip()
    return f"[local-tools:delete_record] 레코드 '{rid}' 삭제 완료(mock 부수효과 실행됨)."


# main.py가 mount할 ASGI 앱. streamable_http_app() 호출 시점에 session_manager가 lazily 생성된다.
mcp_app = mcp.streamable_http_app()
