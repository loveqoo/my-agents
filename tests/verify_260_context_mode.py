"""verify_260 (단위) — 노드별 맥락 모드 carry/clean (스펙 260).

  U1 normalize: context 보존·잡값→carry·기본 carry.
  U2 carry 기준(259 무회귀): 2 carry 노드 → 뒤 노드가 [사용자 입력 + 앞 결과] 모두 봄·최종 누적.
  U3 clean 격리: carry→clean → clean 노드가 **앞 결과만** 입력(사용자 입력 안 봄)·이전 대화 제거(최종 리셋).
  U4 clean+도구 재진입: clean 노드가 도구를 돌 때 재진입은 격리 buffer 위에서(도구 실행·prev 유지, 재-오염 0).

가짜 모델(_model_from_node 몽키패치)로 각 노드가 실제 받은 메시지를 기록해 단언(구조 아닌 동작 검증).
실행: uv run --project packages/api python tests/verify_260_context_mode.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "agent", "src"))

import asyncio  # noqa: E402

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.tools import StructuredTool  # noqa: E402

from agent.runtime import AgentBuildContext  # noqa: E402  (runtime 먼저 — 부트스트랩이 pipeline 완전 초기화)
import agent.flows.pipeline as P  # noqa: E402
from agent.flows.pipeline import LinearPipelineAgent, _text_of, normalize_nodes  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)


MODEL_CFG = {"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}}


def _install_fake(sink, scripted=None):
    """_model_from_node를 가짜로 교체. sink엔 (노드 프롬프트, 받은 [(type,text)...]) 기록.
    scripted: {프롬프트: [AIMessage,...]} 순차 응답(도구 루프용). 없으면 텍스트 응답 1개."""
    counters: dict[str, int] = {}

    def fake(node, ctx):
        prompt = node["prompt"]

        class _F:
            def bind_tools(self, tools):
                return self

            async def ainvoke(self, messages):
                sink.append((prompt, [(type(m).__name__, _text_of(m)) for m in messages]))
                if scripted and prompt in scripted:
                    i = counters.get(prompt, 0)
                    counters[prompt] = i + 1
                    seq = scripted[prompt]
                    return seq[min(i, len(seq) - 1)]
                return AIMessage(content=f"OUT[{prompt}]")

        return _F()

    P._model_from_node = fake


def _ctx(nodes, tools=()):
    return AgentBuildContext(prompt="", model_cfg=MODEL_CFG, tools=list(tools),
                             impl_config={"nodes": nodes})


async def main():
    impl = LinearPipelineAgent()

    # U1 normalize context
    norm = normalize_nodes([
        {"prompt": "a", "context": "clean"},
        {"prompt": "b", "context": "carry"},
        {"prompt": "c", "context": "누가봐도잡값"},
        {"prompt": "d"},
    ])
    check([n["context"] for n in norm] == ["clean", "carry", "carry", "carry"],
          f"U1 context 보존·잡값→carry·기본 carry (got {[n['context'] for n in norm]})")

    orig = P._model_from_node
    try:
        # U2 carry 기준(무회귀)
        sink = []
        _install_fake(sink)
        nodes = [
            {"name": "n1", "prompt": "P1", "model_cfg": MODEL_CFG, "tools": [], "context": "carry"},
            {"name": "n2", "prompt": "P2", "model_cfg": MODEL_CFG, "tools": [], "context": "carry"},
        ]
        g = impl.build_graph(_ctx(nodes))
        out = await g.ainvoke({"messages": [HumanMessage(content="USER_IN")]})
        # n2(carry)가 받은 텍스트 집합
        n2_texts = " | ".join(t for (p, msgs) in sink if p == "P2" for (_, t) in msgs)
        check("USER_IN" in n2_texts and "OUT[P1]" in n2_texts, "U2 carry: 뒤 노드가 사용자 입력+앞 결과 모두 봄")
        check(len(out["messages"]) == 3, f"U2 carry: 최종 누적(USER+OUT1+OUT2=3, got {len(out['messages'])})")

        # U3 clean 격리
        sink = []
        _install_fake(sink)
        nodes = [
            {"name": "n1", "prompt": "P1", "model_cfg": MODEL_CFG, "tools": [], "context": "carry"},
            {"name": "n2", "prompt": "P2", "model_cfg": MODEL_CFG, "tools": [], "context": "clean"},
        ]
        g = impl.build_graph(_ctx(nodes))
        out = await g.ainvoke({"messages": [HumanMessage(content="USER_IN")]})
        n2_texts = " | ".join(t for (p, msgs) in sink if p == "P2" for (_, t) in msgs)
        check("OUT[P1]" in n2_texts, "U3 clean: 앞 노드 결과를 입력으로 받음")
        check("USER_IN" not in n2_texts, "U3 clean: 사용자 입력(쌓인 대화)은 안 봄(격리)")
        # 최종 messages 리셋: 이전(USER_IN, OUT[P1]) 제거 → [Human(OUT[P1]), OUT[P2]] 2개, USER_IN 없음
        contents = [_text_of(m) for m in out["messages"]]
        check(len(out["messages"]) == 2 and "USER_IN" not in " | ".join(contents),
              f"U3 clean: 이전 대화 제거·최종 리셋 (got {contents})")

        # U4 clean + 도구 재진입
        sink = []
        tool = StructuredTool.from_function(func=lambda x="": "TOOL_RESULT", name="probe", description="probe")
        tc = AIMessage(content="", tool_calls=[{"name": "probe", "args": {}, "id": "call_1"}])
        final = AIMessage(content="OUT[P2]")
        _install_fake(sink, scripted={"P2": [tc, final]})
        nodes = [
            {"name": "n1", "prompt": "P1", "model_cfg": MODEL_CFG, "tools": [], "context": "carry"},
            {"name": "n2", "prompt": "P2", "model_cfg": MODEL_CFG, "tools": ["probe"], "context": "clean"},
        ]
        g = impl.build_graph(_ctx(nodes, tools=[tool]))
        out = await g.ainvoke({"messages": [HumanMessage(content="USER_IN")]})
        p2_calls = [msgs for (p, msgs) in sink if p == "P2"]
        check(len(p2_calls) == 2, f"U4 clean+도구: 노드가 2회 호출됨(도구 루프, got {len(p2_calls)})")
        # 1회차(첫 진입): 격리 입력 = OUT[P1]만, USER_IN 없음
        first = " | ".join(t for (_, t) in p2_calls[0])
        check("OUT[P1]" in first and "USER_IN" not in first, "U4 첫 진입: 격리 입력(앞 결과만)")
        # 2회차(재진입): 격리 buffer 위 — prev(OUT[P1]) 유지 + 도구 결과 보임, USER_IN 재유입 없음
        second = " | ".join(t for (_, t) in p2_calls[1])
        check("USER_IN" not in second, "U4 재진입: 쌓인 대화 재-오염 없음(격리 유지)")
        check("TOOL_RESULT" in second, "U4 재진입: 도구 결과가 격리 buffer에 보임")

    finally:
        P._model_from_node = orig

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
