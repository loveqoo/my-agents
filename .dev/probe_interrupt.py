"""격리 probe — langgraph 1.x 에서 도구 내부 interrupt() → pause → Command(resume) 재개가
실제로 어떻게 스트리밍되는지 확인한다(스펙 041 핵심 메커니즘). 인프라 불요(MemorySaver).

확인 항목:
1. 도구가 interrupt() 호출 시 그래프가 멈추고, astream(stream_mode=["messages","updates"])에서
   "__interrupt__" 업데이트가 관측되는가.
2. interrupt 이전의 부수효과(side_effects 리스트)가 pause 시점에 0인가(승인 전 무실행).
3. Command(resume=...)로 같은 thread_id 재개 시 도구가 resume 값을 받아 부수효과를 1회 수행하는가.
4. 비위험(interrupt 없는) 도구 턴은 interrupt 0인가.

실행: uv run python .dev/probe_interrupt.py
"""

import asyncio

from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt

# 가짜 모델 — 실제 LLM 없이 ReAct가 도구를 호출하도록 강제하는 스텁(bind_tools 지원).
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedModel(BaseChatModel):
    """미리 정한 AIMessage 시퀀스를 순서대로 반환. bind_tools는 self 반환(create_react_agent 호환)."""

    responses: list = []
    _idx: dict = {}

    def __init__(self, responses):
        super().__init__()
        object.__setattr__(self, "responses", list(responses))
        object.__setattr__(self, "_idx", {"i": 0})

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        i = self._idx["i"]
        msg = self.responses[min(i, len(self.responses) - 1)]
        self._idx["i"] = i + 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


side_effects: list[str] = []


def dangerous_run(query: str = "") -> str:
    # interrupt는 부수효과 이전에. (승인 전 무실행 불변식)
    decision = interrupt({"action": "github.merge_pr", "args": {"q": query}})
    # 여기는 resume 후에만 도달.
    if isinstance(decision, dict) and decision.get("decision") == "approve":
        side_effects.append("MERGED")
        return "merged ok (모의)"
    return "거부됨 — 실행 안 함"


def safe_run(query: str = "") -> str:
    side_effects.append("READ")
    return "read ok (모의)"


def make_graph(tool_func, tool_name):
    tool = StructuredTool.from_function(func=tool_func, name=tool_name, description="probe tool")
    # FakeChat: 첫 응답은 도구 호출, 재개 후 두번째 응답은 최종 텍스트.
    ai_call = AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": {"query": "x"}, "id": "call_1"}],
    )
    ai_final = AIMessage(content="끝났습니다.")
    model = ScriptedModel([ai_call, ai_final])
    return create_react_agent(model, tools=[tool], checkpointer=MemorySaver())


async def run_dangerous():
    side_effects.clear()
    graph = make_graph(dangerous_run, "merge_pr")
    cfg = {"configurable": {"thread_id": "t1"}}
    interrupts = []
    async for mode, chunk in graph.astream(
        {"messages": [{"role": "user", "content": "merge it"}]},
        config=cfg,
        stream_mode=["messages", "updates"],
    ):
        if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupts.append(chunk["__interrupt__"])
    print("1) pause 시 interrupts 관측:", bool(interrupts), interrupts[0][0].value if interrupts else None)
    print("2) pause 시 side_effects(승인 전 무실행):", side_effects)

    # 상태 확인
    state = await graph.aget_state(cfg)
    print("   state.next (paused 노드):", state.next)

    # 재개 — approve
    final_text = []
    async for mode, chunk in graph.astream(
        Command(resume={"decision": "approve"}),
        config=cfg,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            msg, _meta = chunk
            t = getattr(msg, "content", "")
            if t:
                final_text.append(t)
    print("3) resume(approve) 후 side_effects:", side_effects, "| 최종텍스트:", "".join(final_text))


async def run_reject():
    side_effects.clear()
    graph = make_graph(dangerous_run, "merge_pr")
    cfg = {"configurable": {"thread_id": "t2"}}
    async for mode, chunk in graph.astream(
        {"messages": [{"role": "user", "content": "merge it"}]},
        config=cfg, stream_mode=["messages", "updates"],
    ):
        pass
    print("4) reject 전 side_effects:", side_effects)
    async for mode, chunk in graph.astream(
        Command(resume={"decision": "reject"}), config=cfg, stream_mode=["messages", "updates"],
    ):
        pass
    print("   reject 후 side_effects(무실행 유지):", side_effects)


async def run_safe():
    side_effects.clear()
    graph = make_graph(safe_run, "read_thing")
    cfg = {"configurable": {"thread_id": "t3"}}
    saw_interrupt = False
    async for mode, chunk in graph.astream(
        {"messages": [{"role": "user", "content": "read"}]},
        config=cfg, stream_mode=["messages", "updates"],
    ):
        if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            saw_interrupt = True
    state = await graph.aget_state(cfg)
    print("5) safe 도구: interrupt 관측:", saw_interrupt, "| side_effects:", side_effects, "| state.next:", state.next)


async def main():
    await run_dangerous()
    await run_reject()
    await run_safe()


asyncio.run(main())
