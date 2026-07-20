"""verify_413 — 노드형 사고 다단계 분리(ThoughtChain, 스펙 413).

**결정적**(서버·실모델 불필요) — reasoning을 내는 fake 모델로 2노드 langgraph를 돌려, chat.py 스트림
루프의 **노드 태깅**(langgraph_node)과 FE **노드별 누적**(reasoningSteps→ThoughtChain 판정)을 증명한다.
(라이브 e2e는 실모델의 확률적·느린 thinking 때문에 불안정 — 로직은 이 결정적 테스트가 담보.)

  U1 노드 태깅: 2노드 그래프의 reasoning 프레임이 각 노드(langgraph_node)로 태깅된다.
  U2 축 분리: _stream_reasoning은 reasoning만(본문 미포함, 스펙 410 불변식 유지).
  U3 FE 판정 재현: 노드별 스텝 누적 → 2노드면 ThoughtChain, 1노드면 단일 Think.

실행: uv run --project packages/api python tests/verify_413_node_thinking.py
"""

import asyncio
import os
import sys
from typing import Annotated, TypedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

_fails: list[str] = []
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _S(TypedDict):
    messages: Annotated[list, "add_messages"]


def _steps_from_frames(frames: list[dict]) -> list[dict]:
    """FE onReasoning 노드별 누적 로직 재현(스펙 413) — 마지막 스텝이 같은 노드면 이어붙이고 아니면 새 스텝."""
    steps: list[dict] = []
    for f in frames:
        key = f.get("node") or ""
        if steps and steps[-1]["node"] == key:
            steps[-1]["text"] += f["reasoning"]
        else:
            steps.append({"node": key, "text": f["reasoning"]})
    return steps


async def main() -> None:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages

    from api.chat_sse_frames import _stream_reasoning, _stream_text

    class S(TypedDict):
        messages: Annotated[list, add_messages]

    # reasoning_content를 실은 fake 모델 2개(노드별) — 실모델 확률성 제거.
    m1 = GenericFakeChatModel(
        messages=iter([AIMessage(content="분석 답", additional_kwargs={"reasoning_content": "분석 사고"})])
    )
    m2 = GenericFakeChatModel(
        messages=iter([AIMessage(content="검증 답", additional_kwargs={"reasoning_content": "검증 사고"})])
    )

    async def na(s):
        return {"messages": [await m1.ainvoke(s["messages"])]}

    async def nb(s):
        return {"messages": [await m2.ainvoke(s["messages"])]}

    g = StateGraph(S)
    g.add_node("분석노드", na)
    g.add_node("검증노드", nb)
    g.add_edge(START, "분석노드")
    g.add_edge("분석노드", "검증노드")
    g.add_edge("검증노드", END)
    graph = g.compile()

    # chat.py 스트림 루프 재현: 노드 태그 + _stream_reasoning(축 분리).
    frames: list[dict] = []
    body_has_reasoning = False
    async for _mode, chunk in graph.astream({"messages": [("user", "문제")]}, stream_mode=["messages"]):
        mc, meta = chunk
        node = meta.get("langgraph_node") if isinstance(meta, dict) else None
        r = _stream_reasoning(mc)
        if r:
            frames.append({"reasoning": r, "node": node})
        # 축 분리: 본문(_stream_text)에 사고가 안 섞임.
        if "사고" in _stream_text(mc):
            body_has_reasoning = True

    nodes = [f["node"] for f in frames]
    check("분석노드" in nodes and "검증노드" in nodes, f"U1 reasoning 프레임 노드별 태깅 (got {nodes})")
    check(not body_has_reasoning, "U2 축 분리 — 본문(_stream_text)에 사고 미포함(영속 오염 0)")

    steps = _steps_from_frames(frames)
    check(len(steps) == 2, f"U3a 2노드 → 2스텝(ThoughtChain) (got {len(steps)})")
    check(
        steps[0]["node"] == "분석노드" and steps[1]["node"] == "검증노드",
        f"U3b 스텝이 노드 순서·이름 보존 (got {[s['node'] for s in steps]})",
    )
    # 단일 노드(직접형) 재현 — 1스텝이면 단일 Think.
    single = _steps_from_frames([{"reasoning": "가", "node": "agent"}, {"reasoning": "나", "node": "agent"}])
    check(len(single) == 1 and single[0]["text"] == "가나", "U3c 단일 노드는 1스텝(단일 Think, 직접형 무회귀)")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)
    print("VERIFY413_OK")


if __name__ == "__main__":
    asyncio.run(main())
