"""스펙 054 P1 검증 — MCP 실 런타임 연결(합성 _CANNED 폐기).

`runtime.build_mcp_tools`가 self-host mock MCP(/_remote/mcp/)에 **실제로 붙어** 도구를 가져오고,
호출 결과가 **서버가 실제로 계산한 값**(하드코딩 문자열 아님)인지, SSRF 가드·enabled_tools 필터·
부분 실패 격리가 동작하는지 검증한다. HIL 게이트(⑤)는 verify_041에서 실 도구 위로 별도 검증.

전제: API 서버(uvicorn api.main:app)가 127.0.0.1:8000에 떠 있고, A2A_ALLOWED_HOSTS에 127.0.0.1
포함(루프백 mock 허용). 없으면 전제 실패로 종료(조용한 통과 금지).

검증:
  T1. 실 round-trip — web_search/echo가 서버 실계산값 반환, calls_sink status=ok.
  T2. 결과에 합성 흔적('(모의)') 없음 + _content_text 정규화로 str 반환.
  T3. enabled_tools 필터 — ["echo"]만 주면 echo 도구 하나만 노출.
  T4. SSRF — allowlist 밖 사설 URL 서버는 연결 안 함(스킵), 도달 가능 서버는 살아남음(부분격리).
  T5. graceful — 도달 불가(닫힌 포트) 서버는 스킵, 같이 준 정상 서버 도구는 그대로 빌드.
  T6. transport 게이트 — stdio transport 서버는 제외(유예).
  T7. 소스 grep — runtime.py에 `_CANNED` 0회, 동기 `build_tools(` 0회(폐기 확인, 조건 ③).

실행: A2A_ALLOWED_HOSTS=127.0.0.1 uv run python tests/verify_054_mcp_real_runtime.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import mock_mcp, runtime  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _srv(name=None, url=None, transport="http", enabled=None):
    return {
        "name": name or mock_mcp.MOCK_MCP_SERVER_NAME,
        "url": url if url is not None else mock_mcp.MOCK_MCP_URL,
        "transport": transport,
        "enabled_tools": enabled or [],
        "auth_token": None,
    }


async def _invoke(tool, args):
    """StructuredTool(coroutine) 직접 호출 → 정규화된 결과 문자열."""
    return await tool.ainvoke(args)


async def precondition():
    sink: list[dict] = []
    tools = await runtime.build_mcp_tools([_srv()], sink)
    ok = len(tools) >= 2
    check(ok, f"PRE: live mock MCP 연결 → 도구 {len(tools)}개 빌드")
    if not ok:
        print("\n❌ 전제 실패 — API 서버(127.0.0.1:8000) + A2A_ALLOWED_HOSTS=127.0.0.1 필요. 종료.")
        sys.exit(1)


async def t1_t2_real_roundtrip():
    sink: list[dict] = []
    tools = await runtime.build_mcp_tools([_srv()], sink)
    by = {t.name.split("__", 1)[-1]: t for t in tools}
    ws = by.get("web_search")
    res = await _invoke(ws, {"query": "양자컴퓨팅"})
    check(isinstance(res, str), "T2: 결과가 str로 정규화됨(_content_text)")
    check("검색결과" in res and "양자컴퓨팅" in res, "T1: web_search가 서버 실계산값 반환(쿼리 반영)")
    check("(모의)" not in res, "T2: 결과에 합성 흔적 '(모의)' 없음")
    check(
        len(sink) == 1 and sink[0]["status"] == "ok" and sink[0]["tool"] == "web_search",
        "T1: calls_sink에 status=ok 트레이스 1건",
    )
    # echo: 입력을 그대로 — 서버 왕복 증명
    echo = by.get("echo")
    eres = await _invoke(echo, {"text": "ping-7f3"})
    check(eres == "ping-7f3", "T1: echo 왕복 — 서버가 입력을 그대로 반환")


async def t3_enabled_filter():
    sink: list[dict] = []
    tools = await runtime.build_mcp_tools([_srv(enabled=["echo"])], sink)
    locals_ = {t.name.split("__", 1)[-1] for t in tools}
    check(locals_ == {"echo"}, f"T3: enabled_tools=['echo'] → echo만 노출(실제: {locals_})")


async def t4_ssrf_skip():
    sink: list[dict] = []
    # allowlist 밖 사설 URL(10.0.0.0/8) — 차단 대상. 정상 mock과 함께 줘서 부분격리 확인.
    blocked = _srv(name="evil", url="http://10.1.2.3:9000/mcp/")
    tools = await runtime.build_mcp_tools([blocked, _srv()], sink)
    servers = {t.name.split("__", 1)[0] for t in tools}
    check("evil" not in " ".join(servers), "T4: SSRF 차단(사설 IP) 서버는 연결 안 함")
    check(len(tools) >= 2, "T4: 같이 준 정상 mock 서버 도구는 살아남음(부분 실패 격리)")


async def t5_graceful_down():
    sink: list[dict] = []
    # 닫힌 포트(루프백, allowlist 통과하지만 연결 거부) — get_tools 실패 → 그 서버만 스킵.
    down = _srv(name="down", url="http://127.0.0.1:59999/mcp/")
    tools = await runtime.build_mcp_tools([down, _srv()], sink)
    names = {t.name.split("__", 1)[0] for t in tools}
    check("down" not in names, "T5: 도달 불가 서버는 스킵(크래시 없음)")
    check(len(tools) >= 2, "T5: 같이 준 정상 서버 도구는 그대로 빌드")


async def t6_transport_gate():
    sink: list[dict] = []
    tools = await runtime.build_mcp_tools([_srv(transport="stdio")], sink)
    check(len(tools) == 0, "T6: stdio transport 서버는 제외(유예) — 0 도구")


def t7_source_grep():
    path = os.path.join(ROOT, "packages", "api", "src", "api", "runtime.py")
    src = open(path, encoding="utf-8").read()
    check("_CANNED" not in src, "T7: runtime.py에 _CANNED 0회(합성 폐기, 조건 ③)")
    check("def build_tools(" not in src, "T7: 동기 build_tools( 정의 0회(실연결로 대체)")
    check("async def build_mcp_tools(" in src, "T7: async build_mcp_tools 정의 존재")


def t8_redirect_ssrf_guard():
    """적대 리뷰 H1 회귀 — 리다이렉트-SSRF 가드가 *설정 자체로* 켜져 있는지 단언한다.

    learning(설치≠덮음): "팩토리가 있다"가 아니라 "follow_redirects가 실제로 False"를 단언해야
    가드 우회를 막는다(공인→3xx→사설 우회 + 토큰 재전송). 두 outbound 경로가 배선했는지도 grep.
    """
    from api import net_guard

    client = net_guard.mcp_http_client_factory()
    check(client.follow_redirects is False,
          "T8: mcp_http_client_factory 클라이언트 follow_redirects=False(리다이렉트 미추종)")
    rt = open(os.path.join(ROOT, "packages", "api", "src", "api", "runtime.py"), encoding="utf-8").read()
    bl = open(os.path.join(ROOT, "packages", "api", "src", "api", "blocks.py"), encoding="utf-8").read()
    check("mcp_http_client_factory" in rt, "T8: runtime.build_mcp_tools가 가드 팩토리 배선")
    check("mcp_http_client_factory" in bl, "T8: blocks.discover가 가드 팩토리 배선")


async def main():
    await precondition()
    await t1_t2_real_roundtrip()
    await t3_enabled_filter()
    await t4_ssrf_skip()
    await t5_graceful_down()
    await t6_transport_gate()
    t7_source_grep()
    t8_redirect_ssrf_guard()
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 054 P1 — MCP 실 런타임 연결 전부 통과")


asyncio.run(main())
