"""verify_118 — 관측·측정 계층(Langfuse) inert-until-configured(스펙 118, 방향 2).

사용자 선택 "설정되면 켜지게": 키가 있을 때만 콜백 부착, 없으면 무동작(no-op). 핵심 채팅 경로가 관측
때문에 깨지지 않아야 한다. 콜백이 **실제로 그래프 실행에 전달**되는지(단순 리스트 반환이 아니라 실행에
꽂히는지)까지 최소 그래프로 관통 검증.

  U  inert/설정 게이트·config 병합(기존 보존)·graceful(핸들러 None)·env 스코프.
  I  콜백이 실제 LangGraph astream에 전달돼 이벤트를 받음(전달 관통).

실행: cd packages/api && uv run python ../../tests/verify_118_observability_langfuse.py
"""
import asyncio
import os

from api import observability

_fails = []
def check(c, m):
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


def _clear_keys():
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        os.environ.pop(k, None)


def unit():
    # --- U1 inert: 키 없음 → 콜백 [], config 원본 그대로 ---
    _clear_keys()
    check(observability.is_configured() is False, "U1 키 없음 → is_configured False")
    check(observability.trace_callbacks() == [], "U1 키 없음 → trace_callbacks [](inert)")
    cfg0 = {"configurable": {"thread_id": "t1"}}
    out0 = observability.with_trace(cfg0, name="x", session_id="s", user_id="u")
    check("callbacks" not in out0 and "run_name" not in out0 and "metadata" not in out0,
          "U1 미설정 with_trace → 콜백/메타 미주입(원본 그대로)")

    # --- U2 설정됨(가짜 키) + 가짜 팩토리 → 콜백 병합 + 메타 표준 키 ---
    os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-fake"
    os.environ["LANGFUSE_SECRET_KEY"] = "sk-fake"
    sentinel = object()
    check(observability.is_configured() is True, "U2 키 있음 → is_configured True")
    check(observability.trace_callbacks(lambda: sentinel) == [sentinel],
          "U2 설정+핸들러 → [handler]")
    out = observability.with_trace({"configurable": {"thread_id": "t"}},
                                   name="chat:abc", session_id="sess1", user_id="user1",
                                   _factory=lambda: sentinel)
    check(out.get("callbacks") == [sentinel], "U2 with_trace 콜백 병합")
    check(out.get("run_name") == "chat:abc", "U2 run_name 설정")
    check(out.get("metadata", {}).get("langfuse_session_id") == "sess1",
          "U2 metadata.langfuse_session_id")
    check(out.get("metadata", {}).get("langfuse_user_id") == "user1",
          "U2 metadata.langfuse_user_id")
    check(out.get("configurable", {}).get("thread_id") == "t", "U2 기존 configurable 보존")

    # --- U3 graceful: 설정됐어도 핸들러 생성 실패(None) → [](채팅 안 깨짐) ---
    check(observability.trace_callbacks(lambda: None) == [],
          "U3 핸들러 None(미설치/생성실패) → [](graceful)")

    # --- U4 기존 callbacks/metadata 확장(덮어쓰기 아님) ---
    prior_cb = object()
    out4 = observability.with_trace(
        {"callbacks": [prior_cb], "metadata": {"keep": 1}},
        session_id="s2", _factory=lambda: sentinel,
    )
    check(out4["callbacks"] == [prior_cb, sentinel], "U4 기존 콜백 뒤에 확장(보존)")
    check(out4["metadata"].get("keep") == 1 and out4["metadata"].get("langfuse_session_id") == "s2",
          "U4 기존 metadata 보존 + 표준 키 추가")

    # --- U4b codex 118 [P2] 회귀가드: 비정상 callbacks/metadata에도 with_trace가 안 던짐 ---
    for bad in (None, "notalist"):  # None·비-iterable(CallbackManager 대역)
        try:
            r = observability.with_trace({"callbacks": bad}, _factory=lambda: sentinel)
            ok = isinstance(r.get("callbacks"), list) and sentinel in r["callbacks"]
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"    (with_trace raised on callbacks={bad!r}: {e})")
        check(ok, f"U4b callbacks={bad!r} → 예외 없이 리스트 병합(관측이 채팅 안 깸)")
    try:
        r = observability.with_trace({"metadata": None}, session_id="s", _factory=lambda: sentinel)
        ok = r.get("metadata", {}).get("langfuse_session_id") == "s"
    except Exception:  # noqa: BLE001
        ok = False
    check(ok, "U4b metadata=None → 예외 없이 표준 키 주입")

    # --- U5 실 langfuse 팩토리(설치됨) → 핸들러 생성(가짜 키로 연결 시도 안 함) ---
    real = observability.trace_callbacks()  # 기본 팩토리 = 실제 langfuse
    check(isinstance(real, list) and len(real) == 1,
          f"U5 실 langfuse 핸들러 생성(설정 시) (got {len(real)})")
    _clear_keys()


async def integration():
    """콜백이 실제 astream에 전달돼 이벤트를 받는가(전달 관통) — 실 Langfuse 서버 불요."""
    from typing import TypedDict

    from langchain_core.callbacks.base import BaseCallbackHandler
    from langgraph.graph import END, START, StateGraph

    events = []

    class Recorder(BaseCallbackHandler):
        def on_chain_start(self, serialized, inputs, **kwargs):
            events.append("chain_start")

    os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-fake"
    os.environ["LANGFUSE_SECRET_KEY"] = "sk-fake"
    try:
        class S(TypedDict):
            v: int

        def node(state):
            return {"v": state.get("v", 0) + 1}

        g = StateGraph(S)
        g.add_node("n", node)
        g.add_edge(START, "n")
        g.add_edge("n", END)
        graph = g.compile()

        cfg = observability.with_trace(None, name="itest", _factory=lambda: Recorder())
        check(cfg.get("callbacks") and isinstance(cfg["callbacks"][0], Recorder),
              "I0 with_trace가 Recorder 콜백 주입")
        async for _ in graph.astream({"v": 0}, config=cfg):
            pass
        check("chain_start" in events, "I1 콜백이 실제 그래프 실행 이벤트 수신(전달 관통)")

        # 미설정이면 콜백 전달 0 — 그래프는 정상 실행(무회귀).
        _clear_keys()
        events.clear()
        cfg2 = observability.with_trace(None, name="itest2")
        check("callbacks" not in cfg2, "I2 미설정 → 콜백 미주입")
        async for _ in graph.astream({"v": 0}, config=cfg2):
            pass
        check(events == [], "I2 미설정 실행은 Recorder 미수신(정상 실행·무회귀)")
    finally:
        _clear_keys()


def run():
    unit()
    asyncio.run(integration())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        return False
    print("✅ ALL PASS (VERIFY118_OK)")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
