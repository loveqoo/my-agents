"""스펙 320 검증 — 도구 실행 실패 사유를 인스펙터 trace에 표면화.

검증 사다리(비겹침):
  [U] 단위 — MCP 실패가 calls_sink에 `error` 사유(예외 타입+메시지)·브로커 _build_frame이 res.error
      문자열 보존(불리언 아님)·RAG RagSearchError 사유 전달·비밀 마스킹 백스톱·캡(_ERR_CAP).

실행: uv run --project packages/api python tests/verify_320_tool_error_reason.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def unit_checks() -> None:
    print("[U] 단위 — 실패 사유 포착·마스킹·캡")
    from langchain_core.tools import StructuredTool

    from agent.runtime import InvokeResult
    from api import runtime
    from api.broker.core import _build_frame

    # U1 MCP 실패 — calls_sink에 error 사유(예외 타입 + str(exc)), status=error.
    async def _boom(x: str = "") -> str:
        raise RuntimeError("연결 거부(host down)")

    rt = StructuredTool.from_function(coroutine=_boom, name="boom", description="test")
    sink: list[dict] = []
    wrapped = runtime._wrap_mcp_tool("srv", rt, sink, None)
    asyncio.run(wrapped.ainvoke({"x": "hi"}))
    check(
        len(sink) == 1 and sink[0]["status"] == "error",
        f"U1 실패가 status=error 기록 (got {sink[:1]})",
    )
    err = sink[0].get("error", "")
    check(
        "RuntimeError" in err and "연결 거부" in err,
        f"U1 error에 예외 타입+실제 메시지 (got {err!r})",
    )

    # U1b 성공은 error 필드 없음(무회귀)
    async def _ok(x: str = "") -> str:
        return "정상"

    rt2 = StructuredTool.from_function(coroutine=_ok, name="ok", description="t")
    sink2: list[dict] = []
    asyncio.run(runtime._wrap_mcp_tool("srv", rt2, sink2, None).ainvoke({"x": "hi"}))
    check(sink2[0]["status"] == "ok" and "error" not in sink2[0], "U1b 성공 기록엔 error 필드 없음")

    # U2 브로커 프레임 — res.error 문자열 보존(구 True 불리언 아님).
    res = InvokeResult(text="", error="capability not found")
    inv = _build_frame("broker_invoke:agent:x", "agt_abc", 5, res)
    check(
        isinstance(inv.get("error"), str) and "capability not found" in inv["error"],
        f"U2 브로커 error=사유 문자열(불리언 아님) (got {inv.get('error')!r})",
    )
    # 에러 없으면 error 키 없음(무회귀)
    inv_ok = _build_frame("n", "agt_x", 3, InvokeResult(text="답"))
    check("error" not in inv_ok, "U2b 성공 프레임엔 error 키 없음")

    # U3 RAG 실패 — RagSearchError.tool_msg가 error 사유로.
    rag = runtime.build_rag_tool([{"name": "docs"}], sink3 := [])
    asyncio.run(rag.ainvoke({"query": "", "top_k": 4}))  # 빈 검색어 → RagSearchError("empty")
    check(len(sink3) == 1 and sink3[0]["status"] == "error", f"U3 RAG 실패 기록 (got {sink3[:1]})")
    check(
        "비어" in sink3[0].get("error", ""),
        f"U3 RAG error에 사람 사유(tool_msg) (got {sink3[0].get('error')!r})",
    )

    # U4 마스킹 백스톱 — 사유에 토큰이 섞이면 마스킹(_SECRET_RE).
    async def _leak(x: str = "") -> str:
        raise RuntimeError("인증 실패 token=leaked_abcdef123456 재시도")

    rtl = StructuredTool.from_function(coroutine=_leak, name="leak", description="t")
    sink4: list[dict] = []
    asyncio.run(runtime._wrap_mcp_tool("srv", rtl, sink4, None).ainvoke({"x": "y"}))
    e4 = sink4[0].get("error", "")
    check(
        "leaked_abcdef123456" not in e4 and "«secret»" in e4, f"U4 사유 속 토큰 마스킹 (got {e4!r})"
    )

    # U5 캡 — 긴 사유는 _ERR_CAP로 절단.
    long_msg = "x" * 2000

    async def _long(x: str = "") -> str:
        raise RuntimeError(long_msg)

    rtL = StructuredTool.from_function(coroutine=_long, name="long", description="t")
    sink5: list[dict] = []
    asyncio.run(runtime._wrap_mcp_tool("srv", rtL, sink5, None).ainvoke({"x": "y"}))
    check(
        len(sink5[0].get("error", "")) <= runtime._ERR_CAP + 1,
        f"U5 사유 캡(_ERR_CAP={runtime._ERR_CAP}) (got len {len(sink5[0].get('error', ''))})",
    )

    # U6 어댑터 swallow 회귀 방어(브라우저 rung이 잡은 결함) — langchain-mcp-adapters는 MCP
    # isError를 ToolException으로 만든 뒤 tool.handle_tool_error로 **삼켜 정상 문자열**로 돌린다.
    # 그러면 status=ok로 오기록되고 사유가 사라진다. _wrap_mcp_tool가 rt.handle_tool_error=False로
    # 꺼서 예외가 우리 except로 전파돼 status=error를 기록하는지 단언.
    from langchain_core.tools import ToolException

    async def _isError(x: str = "") -> str:
        raise ToolException("Error executing tool boom: 의도된 실패")

    # handle_tool_error=<메시지 반환> = 어댑터가 세팅하는 swallow 동작 재현(끄지 않으면 status=ok로 샌다).
    rt6 = StructuredTool.from_function(
        coroutine=_isError,
        name="isErr",
        description="t",
        handle_tool_error=lambda e: f"Error executing tool boom: {e}",
    )
    sink6: list[dict] = []
    asyncio.run(runtime._wrap_mcp_tool("srv", rt6, sink6, None).ainvoke({"x": "y"}))
    check(
        sink6[0]["status"] == "error" and "의도된 실패" in sink6[0].get("error", ""),
        f"U6 어댑터 swallow 무력화(status=error+사유 보존) (got {sink6[:1]})",
    )

    # U6b 성공 경로 무회귀 — handle_tool_error를 꺼도 정상 반환은 그대로 status=ok.
    async def _ok6(x: str = "") -> str:
        return "정상값"

    rt6b = StructuredTool.from_function(
        coroutine=_ok6, name="ok6", description="t", handle_tool_error=lambda e: "swallowed"
    )
    sink6b: list[dict] = []
    asyncio.run(runtime._wrap_mcp_tool("srv", rt6b, sink6b, None).ainvoke({"x": "y"}))
    check(
        sink6b[0]["status"] == "ok" and "error" not in sink6b[0], "U6b 성공 경로 무회귀(status=ok)"
    )

    # U7 브로커 MCP 경로도 어댑터 swallow 무력화(codex 320 P1 — 직접 경로만 고치면 형제 표면 비일관).
    # 브로커 provider.invoke가 row.tool.handle_tool_error를 끄고 예외를 잡아 res.error에 사유를 싣는지.
    from api.broker.providers.mcp import McpProvider, _McpBacking

    async def _bfail(reason: str = "") -> str:
        raise ToolException(f"Error executing tool bfail: 의도된 실패: {reason}")

    rt7 = StructuredTool.from_function(
        coroutine=_bfail,
        name="bfail",
        description="t",
        handle_tool_error=lambda e: f"Error executing tool bfail: {e}",
    )
    row = _McpBacking("srv", "bfail", rt7, None)
    res = asyncio.run(McpProvider(None).invoke(row, {"reason": "x"}))
    check(
        res.error and "의도된 실패" in res.error,
        f"U7 브로커 MCP 실패 사유 보존(res.error) (got {res.error!r})",
    )

    # U7b 브로커 성공 경로 무회귀 — 정상 반환은 error=None.
    async def _bok(reason: str = "") -> str:
        return "정상"

    rt7b = StructuredTool.from_function(
        coroutine=_bok, name="bok", description="t", handle_tool_error=lambda e: "swallowed"
    )
    res_b = asyncio.run(
        McpProvider(None).invoke(_McpBacking("srv", "bok", rt7b, None), {"reason": "x"})
    )
    check(res_b.error is None and res_b.text == "정상", "U7b 브로커 성공 경로 무회귀(error=None)")

    # U8 마스킹 강화(codex 320 P1b) — 라벨 없는 자격증명 형태(URL userinfo·Basic)도 사유에서 마스킹.
    from api.memory import _sanitize

    leak_url = _sanitize("401 from https://alice:s3cr3tPass@example.com/mcp 연결 거부")
    check(
        "s3cr3tPass" not in leak_url
        and "alice:s3cr3tPass" not in leak_url
        and "example.com" in leak_url,
        f"U8 URL userinfo 마스킹(호스트 보존) (got {leak_url!r})",
    )
    leak_basic = _sanitize("Authorization header rejected: Basic dXNlcjpwYXNzd29yZA==")
    check("dXNlcjpwYXNzd29yZA" not in leak_basic, f"U8 Basic 자격증명 마스킹 (got {leak_basic!r})")
    # U8b 오탐 방지 — userinfo 없는 base_url은 그대로(비밀 아님).
    keep = _sanitize("base_url=http://h:8000/v1 model=gpt-x")
    check("http://h:8000/v1" in keep, f"U8b userinfo 없는 URL은 미마스킹 (got {keep!r})")


def main() -> None:
    unit_checks()
    print(f"\n{len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)
    print("VERIFY320_OK — 도구 실패 사유 표면화(MCP·브로커·RAG·마스킹·캡) 정착")


if __name__ == "__main__":
    main()
