"""격리 probe — 스펙 092. Playground 채팅 스트림에서 ToolMessage(도구 원본 응답)가
stream_mode="messages"로 흘러나올 때 실제 어떤 타입/메타로 오는지 실측한다(인프라 불요, MemorySaver).

확인 항목(chat.py:659-664의 누수 가설 검증):
1. ToolNode가 낸 ToolMessage가 messages 모드 청크로 흘러나오는가.
2. 그렇다면 msg_chunk.type == "tool" 인가(AIMessageChunk는 "ai")? content는 도구 원본인가?
3. _meta["langgraph_node"]로 model 노드("agent"/"model") vs tools 노드 구별이 되는가?
4. 즉 "type=='tool' 게이트"로 본문에서 도구 원본만 거를 수 있는가 — 거짓양성 없이.

실행: uv run python .dev/probe_092_tool_message_stream.py
"""

import asyncio

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

RAW = "RAW_TOOL_OUTPUT::섭씨23도_맑음"  # 도구 원본 응답(채팅 본문에 새면 안 됨)
FINAL = "오늘 날씨는 맑고 23도입니다."  # 모델 최종 추론(채팅 본문에 나와야 함)


class ScriptedModel(BaseChatModel):
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


def get_weather(query: str = "") -> str:
    return RAW


def make_graph():
    tool = StructuredTool.from_function(func=get_weather, name="get_weather", description="날씨")
    ai_call = AIMessage(
        content="", tool_calls=[{"name": "get_weather", "args": {"query": "서울"}, "id": "c1"}]
    )
    ai_final = AIMessage(content=FINAL)
    return create_react_agent(ScriptedModel([ai_call, ai_final]), tools=[tool], checkpointer=MemorySaver())


async def main():
    graph = make_graph()
    cfg = {"configurable": {"thread_id": "p92"}}
    print(f"{'mode':9} {'type':18} {'node':12} content")
    print("-" * 80)
    leaked_raw = False
    emitted_final = False
    async for mode, chunk in graph.astream(
        {"messages": [{"role": "user", "content": "서울 날씨"}]},
        config=cfg,
        stream_mode=["messages", "updates"],
    ):
        if mode != "messages":
            continue
        msg, meta = chunk
        node = (meta or {}).get("langgraph_node", "?")
        text = getattr(msg, "content", "")
        cls = type(msg).__name__
        mtype = getattr(msg, "type", "?")
        print(f"{mode:9} {mtype+'/'+cls:18} {node:12} {text!r}")
        if text and RAW in (text if isinstance(text, str) else str(text)):
            leaked_raw = True
        if text and FINAL in (text if isinstance(text, str) else str(text)):
            emitted_final = True

    print("-" * 80)
    print("[검증] ToolMessage 원본이 messages 스트림에 흘러나옴(누수 재현):", leaked_raw)
    print("[검증] 모델 최종 텍스트도 흘러나옴(본문에 남겨야 함):", emitted_final)
    print("[결론] type=='tool' 게이트로 원본만 거르고 'ai'는 보존 가능:", leaked_raw and emitted_final)


asyncio.run(main())
