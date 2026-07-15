"""verify_315 (단위) — 파이프라인 실행 노드 도구 루프 상한 + 우아한 마무리 (스펙 315).

배경(실측): plan-execute-demo에 "스트리밍 UI 최신 동향" 질의 시 실행 노드가 wiki_search/wiki_page를
14회 반복(수렴 실패)하다 모델 서버 연결이 끊겨 답이 깨졌다. 상한을 둬 러너웨이를 막고, 상한 도달 시
도구를 떼고(unbound) 답을 강제(우아한 마무리)한다.

  T1 수렴 안 하는 모델(항상 tool_call)도 도구 호출이 _TOOL_ROUNDS_CAP회로 상한 걸린다.
  T2 상한 도달 후 그래프가 에러 없이 종료하고 최종 답(tool_calls 없는 AI)을 낸다(우아한 마무리).
  T3 상한 전(도구 몇 번)에 스스로 답하는 모델은 상한과 무관하게 정상 조기 종료(무회귀).

실행: uv run --project packages/api python tests/verify_315_tool_loop_cap.py
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "agent", "src"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.tools import StructuredTool  # noqa: E402

from agent.runtime import AgentBuildContext  # noqa: E402  (먼저 — 빌트인 부트스트랩 완료)
import agent.flows.pipeline as pl  # noqa: E402, I001
from agent.flows.pipeline import _TOOL_ROUNDS_CAP, LinearPipelineAgent, _text_of  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)


MODEL_CFG = {"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}}
TOOL = "web-fetch__wiki_search"


def _tool():
    return StructuredTool.from_function(func=lambda query="": "검색결과", name=TOOL, description="검색")


class _Bound:
    """bind_tools 결과 — stop_after회까지만 tool_call 방출, 이후엔 최종 답(조기 수렴 시뮬용)."""
    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.calls = 0
    async def ainvoke(self, messages):
        self.calls += 1
        if self.stop_after is not None and self.calls > self.stop_after:
            return AIMessage(content="조기 최종 답변")
        return AIMessage(content="", tool_calls=[{"name": TOOL, "args": {"query": "x"}, "id": "c" + uuid.uuid4().hex[:8]}])


class _FakeModel:
    """unbound 모델 — 도구 없이 호출되면(상한 도달) 최종 답. bind_tools는 _Bound 반환.
    rogue_unbound=True면 unbound인데도 tool_calls를 계속 낸다(느슨한 provider 흉내 — codex P1 방어 검증)."""
    def __init__(self, stop_after=None, rogue_unbound=False):
        self.stop_after = stop_after
        self.rogue_unbound = rogue_unbound
        self.bound = None
    def bind_tools(self, tools):
        self.bound = _Bound(self.stop_after)
        return self.bound
    async def ainvoke(self, messages):
        if self.rogue_unbound:
            return AIMessage(content="", tool_calls=[{"name": TOOL, "args": {"query": "x"}, "id": "r" + uuid.uuid4().hex[:8]}])
        return AIMessage(content="상한 도달 — 지금까지 찾은 것으로 정리한 최종 답변")


def _run(stop_after=None, rogue_unbound=False):
    fake = _FakeModel(stop_after=stop_after, rogue_unbound=rogue_unbound)
    pl._model_from_node = lambda node, ctx: fake  # noqa: ARG005
    ctx = AgentBuildContext(
        prompt="", model_cfg=MODEL_CFG, tools=[_tool()],
        impl_config={"nodes": [{"name": "실행", "prompt": "검색해 답하라", "model_cfg": MODEL_CFG, "tools": [TOOL]}]},
    )
    g = LinearPipelineAgent().build_graph(ctx)
    result = asyncio.run(g.ainvoke({"messages": [HumanMessage(content="검색해줘")]}))
    return result["messages"]


def main():
    _orig = pl._model_from_node
    try:
        # ── T1/T2: 수렴 안 하는 모델(항상 tool_call) ──
        msgs = _run(stop_after=None)
        tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
        check(len(tool_msgs) == _TOOL_ROUNDS_CAP,
              f"T1 무한 tool_call 모델도 도구 호출 {len(tool_msgs)}회로 상한({_TOOL_ROUNDS_CAP})")
        last = msgs[-1]
        check(not getattr(last, "tool_calls", None) and "최종 답변" in _text_of(last),
              "T2 상한 후 에러 없이 최종 답(도구 없이 강제 수렴)")

        # ── T3: 도구 2번 후 스스로 답하는 모델 → 조기 종료(상한 무관, 무회귀) ──
        msgs3 = _run(stop_after=2)
        tool3 = [m for m in msgs3 if isinstance(m, ToolMessage)]
        check(len(tool3) == 2 and not getattr(msgs3[-1], "tool_calls", None),
              f"T3 조기 수렴 모델은 도구 {len(tool3)}회(상한 전)에 정상 종료")

        # ── T4(codex P1): unbound인데도 tool_calls를 계속 내는 느슨한 provider에도 airtight 종료 ──
        msgs4 = _run(rogue_unbound=True)
        tool4 = [m for m in msgs4 if isinstance(m, ToolMessage)]
        check(len(tool4) == _TOOL_ROUNDS_CAP and not getattr(msgs4[-1], "tool_calls", None),
              f"T4 rogue unbound(계속 tool_calls)도 도구 {len(tool4)}회로 종료(tool_calls 강제 제거)")
    finally:
        pl._model_from_node = _orig

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)
    print("VERIFY315_OK — 도구 루프 상한 + 우아한 마무리 정착")


if __name__ == "__main__":
    main()
