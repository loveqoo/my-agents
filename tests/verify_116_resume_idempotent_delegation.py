"""스펙 116 검증 — 재개 시 선행 위임 결과 보존(멱등 재개, codex 102 [P1] 봉합).

다중 위임 중 뒤 cap이 승인 interrupt하면, 재개 시 delegate 노드가 재실행돼도 **선행 read-only cap은
재호출되지 않아야** 한다(각 cap = 자기 노드 실행 = 체크포인트 경계 → done에 커밋됨).

  [H] 실 그래프 + interrupt/resume — read-only cap invoke 횟수가 재개 후에도 정확히 1(중복 읽기 0).
      (구 구조였다면 재개 시 노드 처음부터 재실행으로 2회 — 이 테스트가 그 차이를 잡는다.)

실행: cd packages/agent && uv run python ../../tests/verify_116_resume_idempotent_delegation.py
"""
import sys

import agent.runtime  # noqa: F401 — runtime↔orchestrate 부트스트랩(verify_115 교훈)

_fails = []
def check(c, m):
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


async def main_checks():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command
    from agent.flows.orchestrate import OrchestrationAgentBase
    from agent.runtime import AgentBuildContext, Capability, InvokeResult

    READ, GATED = "rag:read", "mcp:gated/act"

    GATED2 = "mcp:gated/act2"

    def _is_gated(cid):
        return cid.startswith("mcp:gated")

    class CountingBroker:
        """invoke·discover 횟수를 센다. mcp:gated* 는 전송 이전 interrupt(스펙 101)."""
        def __init__(self, caps):
            self.counts: dict[str, int] = {}
            self.sideeffects = 0  # 승인 후 실제 '실행' 횟수
            self.discover_calls = 0
            self.caps = caps
        async def discover(self, query, *, limit=5):
            self.discover_calls += 1
            return self.caps[:limit]
        async def describe(self, cap_id):
            return next(c for c in self.caps if c.id == cap_id)
        async def invoke(self, cap_id, args):
            self.counts[cap_id] = self.counts.get(cap_id, 0) + 1
            if _is_gated(cap_id):
                from langgraph.types import interrupt
                decision = interrupt({"cap": cap_id})  # 전송 이전 pause
                if not (isinstance(decision, dict) and decision.get("decision") == "approve"):
                    return InvokeResult(text="거부됨", trust="untrusted")
                self.sideeffects += 1  # 승인된 경우에만(부수효과 1회 불변식)
                return InvokeResult(text=f"게이트 실행됨({cap_id})", trust="untrusted")
            return InvokeResult(text=f"읽기결과({cap_id})", trust="untrusted")

    class FixedOrder(OrchestrationAgentBase):
        """select=순서 유지 → discover 순서대로 순차 위임."""
        NAME = "t116"
        DESCRIPTION = "test"
        DISCOVER_LIMIT = 10
        def select(self, query, candidates):
            return list(candidates)

    _READ_CAP = Capability(id=READ, kind="rag", name="읽기", hook="문서 읽기")
    _GATED_CAP = Capability(id=GATED, kind="mcp", name="게이트", hook="위험 동작")
    _GATED2_CAP = Capability(id=GATED2, kind="mcp", name="게이트2", hook="위험 동작2")

    broker = CountingBroker([_READ_CAP, _GATED_CAP])
    ctx = AgentBuildContext(
        prompt="오케스트레이터", model_cfg={"base_url": "http://x", "model_id": "mock-llm"},
        tools=[], broker=broker, checkpointer=MemorySaver(),
    )
    graph = FixedOrder().build_graph(ctx)
    cfg = {"configurable": {"thread_id": "v116-h1"}}

    # 1) 초기 실행 — GATED에서 interrupt. READ는 이미 완료·커밋.
    interrupted = None
    async for mode, chunk in graph.astream(
        {"messages": [("user", "무엇이든 요청")]}, config=cfg, stream_mode=["updates"]
    ):
        if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupted = chunk["__interrupt__"][0].value
    check(interrupted is not None and interrupted.get("cap") == GATED, "H1 GATED에서 interrupt(전송 이전)")
    check(broker.counts.get(READ) == 1, f"H1 pause 시점 READ invoke 1회 (got {broker.counts.get(READ)})")
    check(broker.sideeffects == 0, f"H1 pause 시점 GATED 부수효과 0 (got {broker.sideeffects})")

    # 2) 승인 재개 — delegate 노드 재실행되나 READ는 done에 커밋돼 **재호출 안 됨**.
    #    synthesize의 모델 호출은 이 테스트 관심 밖(가짜 model_cfg) — delegate가 counts·state를 이미
    #    커밋하므로 모델 연결 에러는 삼키고 delegate 결과만 검증한다.
    try:
        async for _ in graph.astream(Command(resume={"decision": "approve"}), config=cfg, stream_mode=["updates"]):
            pass
    except Exception:  # noqa: BLE001 — synthesize 모델 호출 실패(delegate 이후, 관심 밖)
        pass
    check(broker.counts.get(READ) == 1,
          f"H2 재개 후에도 READ invoke 정확히 1회(선행 read-only 재호출 0 — 스펙 116 핵심) (got {broker.counts.get(READ)})")
    check(broker.sideeffects == 1, f"H2 GATED 부수효과 정확히 1회(재실행돼도, 스펙 101 보존) (got {broker.sideeffects})")

    # 3) 최종 상태에 두 결과가 fold돼 delegated에 담김(완주).
    snap = graph.get_state(cfg)
    delegated = snap.values.get("delegated") or ""
    check("읽기결과" in delegated and "게이트 실행됨" in delegated,
          "H3 최종 delegated에 READ+GATED 결과 모두 fold")
    check("⟦BEGIN " in delegated, "H3 다중 결과 → nonce 펜스(스펙 115) 유지")

    # --- H4: 첫 cap이 gated여도 재개 시 재-discover 안 됨(codex 116 [P1] 봉합) ---
    #     plan이 pending을 invoke 이전에 커밋하므로, 첫 cap interrupt→재개에서 discover가 다시 안 돌아
    #     승인 대상이 뒤바뀔 여지가 없다(discover_calls == 1).
    b4 = CountingBroker([_GATED_CAP])  # 단일 gated — 첫(=유일) cap이 interrupt
    g4 = FixedOrder().build_graph(AgentBuildContext(
        prompt="o", model_cfg={"base_url": "http://x", "model_id": "m"}, tools=[],
        broker=b4, checkpointer=MemorySaver()))
    c4 = {"configurable": {"thread_id": "v116-h4"}}
    async for mode, chunk in g4.astream({"messages": [("user", "요청")]}, config=c4, stream_mode=["updates"]):
        pass
    check(b4.discover_calls == 1, f"H4 초기 실행 discover 1회 (got {b4.discover_calls})")
    try:
        async for _ in g4.astream(Command(resume={"decision": "approve"}), config=c4, stream_mode=["updates"]):
            pass
    except Exception:  # noqa: BLE001
        pass
    check(b4.discover_calls == 1,
          f"H4 첫 cap gated여도 재개 시 재-discover 0(승인 대상 고정, codex 116 P1) (got {b4.discover_calls})")
    check(b4.sideeffects == 1, f"H4 gated 부수효과 정확히 1회 (got {b4.sideeffects})")

    # --- H5: 다중 gated [GATED, GATED2] — 첫 승인 재개가 두 번째 gated에서 다시 멈춤(fail-closed) ---
    #     제품 승인 파이프라인(chat.py resume)은 2번째 interrupt를 새 승인 row로 아직 안 띄운다(101/102
    #     다중 interrupt OUT). 그래프 계약상 중요한 것은 **두 번째 gated의 부수효과가 미승인 상태로 실행되지
    #     않음**(fail-closed) — 이 안전 불변식을 실측한다.
    b5 = CountingBroker([_GATED_CAP, _GATED2_CAP])
    g5 = FixedOrder().build_graph(AgentBuildContext(
        prompt="o", model_cfg={"base_url": "http://x", "model_id": "m"}, tools=[],
        broker=b5, checkpointer=MemorySaver()))
    c5 = {"configurable": {"thread_id": "v116-h5"}}
    first = None
    async for mode, chunk in g5.astream({"messages": [("user", "요청")]}, config=c5, stream_mode=["updates"]):
        if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            first = chunk["__interrupt__"][0].value
    check(first and first.get("cap") == GATED, "H5 첫 gated에서 interrupt")
    second = None
    async for mode, chunk in g5.astream(Command(resume={"decision": "approve"}), config=c5, stream_mode=["updates"]):
        if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            second = chunk["__interrupt__"][0].value
    check(second and second.get("cap") == GATED2,
          "H5 첫 승인 재개가 두 번째 gated에서 다시 interrupt(자기 루프로 도달)")
    check(b5.sideeffects == 1,
          f"H5 두 번째 gated는 미승인 → 부수효과 미실행(fail-closed, 승인된 1건만) (got {b5.sideeffects})")


async def _run():
    await main_checks()


if __name__ == "__main__":
    import asyncio
    asyncio.run(_run())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS (VERIFY116_OK)")
