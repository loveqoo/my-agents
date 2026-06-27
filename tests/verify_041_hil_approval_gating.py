"""스펙 041 검증 — HIL 승인 게이팅 (인프라 경량, 실 게이트 코드 경로).

**핵심 불변식**: approver=admin 도구(repo.merge·k8s.write)의 부수효과(합성: canned 반환 +
calls_sink 트레이스 emit)는 **승인 전에는 0**, 거부면 실행 안 함. 게이트는 *실행 결정* 자체를
부수효과 이전에 interrupt로 막는다(실 MCP로 바뀌어도 동일 유효).

실 `runtime.build_tools`(게이트 정책+interrupt 래핑)와 `agent.main.build_agent`(checkpointer 전달)를
그대로 태운다. 모델만 스크립트 스텁(LLM 불요). 체크포인터는 MemorySaver로 격리(durable Postgres
연결은 lifespan probe·브라우저 e2e에서 별도 확인 — 게이트 로직은 체크포인터 종류와 무관).

검증:
  G1. 위험 도구 호출 → __interrupt__ 발생 + pause 시 calls_sink 0 (승인 전 무실행).
  G2. resume(approve) → 도구 실행(calls_sink 1) + 최종 답변.
  G3. resume(reject) → 도구 미실행(calls_sink 0) + 거부 문자열로 마무리.
  G4. 비위험(read) 도구 → interrupt 0, 즉시 실행(calls_sink 1) — 회귀.
  G5. 무도구 턴 → interrupt 0.
  G6. build_agent(checkpointer=) 전달 배선 + None이면 무체크포인터(무회귀).
  G7. 정책 맵 _APPROVAL_ACTIONS = admin 권한 2개 정확히, read 도구는 미포함.

실행: uv run python tests/verify_041_hil_approval_gating.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from agent.main import build_agent  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from langgraph.types import Command  # noqa: E402

from api import runtime  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class ScriptedModel(BaseChatModel):
    """미리 정한 AIMessage 시퀀스를 순서대로 반환(bind_tools=self). create_react_agent 호환 스텁."""

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


def _graph_calling(server, tool_name, calls_sink):
    """(server,tool)을 1회 호출하고 마무리하는 ReAct 그래프 + 실 build_tools 게이트."""
    tools = runtime.build_tools([(server, tool_name)], calls_sink)
    safe = runtime._safe_name(server, tool_name)
    ai_call = AIMessage(
        content="", tool_calls=[{"name": safe, "args": {"query": "x"}, "id": "c1"}]
    )
    ai_final = AIMessage(content="처리했습니다.")
    model = ScriptedModel([ai_call, ai_final])
    return create_react_agent(model, tools=tools, checkpointer=MemorySaver())


async def _stream(graph, payload, cfg):
    """astream(messages+updates) → (interrupt_payload|None, streamed_text)."""
    interrupted = None
    text = []
    async for mode, chunk in graph.astream(
        payload, config=cfg, stream_mode=["messages", "updates"]
    ):
        if mode == "messages":
            msg, _meta = chunk
            t = getattr(msg, "content", "")
            if t:
                text.append(t)
        elif mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupted = chunk["__interrupt__"][0].value
    return interrupted, "".join(text)


async def g1_g2_approve():
    sink: list[dict] = []
    graph = _graph_calling("github", "merge_pr", sink)
    cfg = {"configurable": {"thread_id": "g1"}}
    interrupted, _ = await _stream(graph, {"messages": [{"role": "user", "content": "merge"}]}, cfg)
    check(interrupted is not None, "G1: 위험 도구(github.merge_pr) 호출 → interrupt 발생")
    check(
        interrupted is not None and interrupted.get("permission") == "repo.merge",
        "G1: interrupt payload에 permission=repo.merge",
    )
    check(len(sink) == 0, "G1: pause 시 calls_sink 0 (승인 전 부수효과 무emit)")

    _, text = await _stream(graph, Command(resume={"decision": "approve"}), cfg)
    check(len(sink) == 1 and sink[0]["tool"] == "merge_pr", "G2: approve 재개 → 도구 실행(calls_sink 1)")
    check("처리했습니다" in text, "G2: approve 후 최종 답변 스트리밍")


async def g3_reject():
    sink: list[dict] = []
    graph = _graph_calling("kubernetes", "scale", sink)
    cfg = {"configurable": {"thread_id": "g3"}}
    interrupted, _ = await _stream(graph, {"messages": [{"role": "user", "content": "scale"}]}, cfg)
    check(
        interrupted is not None and interrupted.get("permission") == "k8s.write",
        "G3: kubernetes.scale → interrupt(k8s.write)",
    )
    check(len(sink) == 0, "G3: pause 시 calls_sink 0")
    _, _text = await _stream(graph, Command(resume={"decision": "reject"}), cfg)
    check(len(sink) == 0, "G3: reject 재개 → 도구 미실행(calls_sink 0, 부수효과 0)")


async def g4_read_tool():
    sink: list[dict] = []
    graph = _graph_calling("github", "get_pr", sink)  # read 도구 — 정책 미포함
    cfg = {"configurable": {"thread_id": "g4"}}
    interrupted, _ = await _stream(graph, {"messages": [{"role": "user", "content": "read pr"}]}, cfg)
    check(interrupted is None, "G4: 비위험(read) 도구 → interrupt 0")
    check(len(sink) == 1 and sink[0]["tool"] == "get_pr", "G4: read 도구 즉시 실행(calls_sink 1) — 회귀")


async def g5_no_tool():
    sink: list[dict] = []
    tools = runtime.build_tools([("github", "merge_pr")], sink)  # 위험 도구 wiring돼 있어도
    model = ScriptedModel([AIMessage(content="도구 없이 바로 답합니다.")])  # 모델이 호출 안 하면
    graph = create_react_agent(model, tools=tools, checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "g5"}}
    interrupted, text = await _stream(graph, {"messages": [{"role": "user", "content": "hi"}]}, cfg)
    check(interrupted is None, "G5: 무도구 턴 → interrupt 0")
    check(len(sink) == 0 and "바로 답합니다" in text, "G5: 무도구 턴 정상 응답(부수효과 0)")


def g6_build_agent_wiring():
    saver = MemorySaver()
    cfg = {"base_url": "http://x/v1", "model_id": "m", "params": {}}
    g_with = build_agent("p", {}, [], cfg, checkpointer=saver)
    check(g_with.checkpointer is saver, "G6: build_agent(checkpointer=) → 그래프에 그대로 전달")
    g_without = build_agent("p", {}, [], cfg)
    check(not g_without.checkpointer, "G6: checkpointer 미지정 → 무체크포인터(기존 무상태, 무회귀)")


def g7_policy_map():
    pol = runtime._APPROVAL_ACTIONS
    check(
        pol == {("github", "merge_pr"): "repo.merge", ("kubernetes", "scale"): "k8s.write"},
        "G7: 정책 맵 = admin 권한 2개 정확히",
    )
    check(("github", "get_pr") not in pol, "G7: read 도구(get_pr)는 게이트 정책에 미포함")


async def main():
    await g1_g2_approve()
    await g3_reject()
    await g4_read_tool()
    await g5_no_tool()
    g6_build_agent_wiring()
    g7_policy_map()
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 041 게이트 시맨틱 전부 통과")


asyncio.run(main())
