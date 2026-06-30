"""verify_092 — 채팅 본문서 도구(블록) 원본 응답 숨김 (스펙 092).

검증 ①(단위 시맨틱): runtime.is_tool_message 술어 — ToolMessage/ToolMessageChunk만 True.
검증 ②(실 그래프 통합): 실제 ReAct 그래프(create_react_agent — 제품 build_agent가 감싸는 프리빌트)를
  stream_mode="messages"로 돌려 event_stream과 *동일한 필터 코드경로*를 적용 → 도구 원본(RAW)이
  yield 프레임·acc 양쪽에서 빠지고 모델 최종(FINAL)은 남는지, calls_sink엔 도구 결과가 보존되는지 단언.

실행: uv run python tests/verify_092_tool_chunk_filter.py
(적대는 codex. 단위 술어 + 전체 흐름 비겹침.)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "api" / "src"))

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
    ToolMessageChunk,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from api import runtime  # noqa: E402

passed = 0
failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  ✗ " + label)


# ----------------------------- ① 술어 단위 -----------------------------
check(runtime.is_tool_message(ToolMessage(content="raw", tool_call_id="c1")), "ToolMessage → True")
check(
    runtime.is_tool_message(ToolMessageChunk(content="raw", tool_call_id="c1")),
    "ToolMessageChunk(스트리밍 분할) → True",
)
check(not runtime.is_tool_message(AIMessage(content="hi")), "AIMessage → False")
check(not runtime.is_tool_message(AIMessageChunk(content="hi")), "AIMessageChunk → False")
check(not runtime.is_tool_message(HumanMessage(content="hi")), "HumanMessage → False")
check(not runtime.is_tool_message(object()), "type 없는 객체 → False(getattr 기본값)")
check(not runtime.is_tool_message(AIMessage(content="")), "빈 content AIMessage → False(타입만 본다)")

# ① content 정규화(codex P1): content가 content-block 리스트여도 str 보장 — 본문 sink가
# "".join(acc)로 합치므로 list가 새면 TypeError. _content_text가 막는다.
check(runtime._content_text("hi") == "hi", "str content → 그대로")
check(
    runtime._content_text([{"type": "text", "text": "가"}, {"type": "text", "text": "나"}]) == "가\n나",
    "content-block 리스트 → 텍스트 결합(str)",
)
check(runtime._content_text("") == "" and runtime._content_text(None) == "", "빈/None → 빈 str")


# ----------------------------- ② 실 그래프 통합 -----------------------------
RAW = "RAW_TOOL_OUTPUT::섭씨23도_맑음"  # 도구 원본 — 본문/acc서 빠져야
FINAL = "오늘 날씨는 맑고 23도입니다."  # 모델 최종 — 본문/acc에 남아야


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


def _weather(query: str = "") -> str:
    return RAW


async def integration() -> None:
    calls_sink: list[dict] = []
    base = StructuredTool.from_function(func=_weather, name="get_weather", description="날씨")
    # 제품과 동일하게 _wrap_mcp_tool로 감싸 calls_sink 적재 경로를 실제로 탄다(관측성 보존 단언용).
    wrapped = runtime._wrap_mcp_tool("memserver", base, calls_sink)
    tool_name = wrapped.name  # _safe_name("memserver","get_weather") == "memserver__get_weather"

    ai_call = AIMessage(
        content="", tool_calls=[{"name": tool_name, "args": {"query": "서울"}, "id": "c1"}]
    )
    ai_final = AIMessage(content=FINAL)
    graph = create_react_agent(
        ScriptedModel([ai_call, ai_final]), tools=[wrapped], checkpointer=MemorySaver()
    )

    # event_stream(chat.py)의 messages 분기와 동일한 필터 코드경로를 그대로 재현.
    acc: list[str] = []
    frames: list[str] = []
    async for stream_mode, chunk in graph.astream(
        {"messages": [{"role": "user", "content": "서울 날씨"}]},
        config={"configurable": {"thread_id": "v92"}},
        stream_mode=["messages", "updates"],
    ):
        if stream_mode != "messages":
            continue
        msg_chunk, _meta = chunk
        if runtime.is_tool_message(msg_chunk):  # ← 검증 대상 게이트
            continue
        # 실 sink(chat.py)와 동일하게 _content_text로 str 정규화(codex P1).
        text = runtime._content_text(getattr(msg_chunk, "content", ""))
        if text:
            acc.append(text)
            frames.append(text)

    body = "".join(acc)  # list content가 새면 여기서 TypeError → 회귀 가드
    check(all(RAW not in f for f in frames), "RAW가 yield 프레임에 없음(도구 원본 미노출)")
    check(RAW not in body, "RAW가 acc(영속/메모리/토큰 본문)에 없음")
    check(FINAL in body, "FINAL(모델 최종 추론)은 본문에 보존")
    check(any(c.get("result") == RAW for c in calls_sink), "calls_sink엔 도구 원본 보존(인스펙터 관측성)")
    check(len(calls_sink) == 1, "도구 1회 호출이 calls_sink에 정확히 1건")


async def integration_content_blocks() -> None:
    """codex P1 회귀: 모델 최종 메시지의 content가 content-block 리스트인 경우(Anthropic 등),
    도구 필터 후에도 본문 합치기(`"".join`)가 크래시 없이 텍스트를 보존하는지."""
    calls_sink: list[dict] = []
    base = StructuredTool.from_function(func=_weather, name="get_weather", description="날씨")
    wrapped = runtime._wrap_mcp_tool("memserver", base, calls_sink)
    ai_call = AIMessage(
        content="", tool_calls=[{"name": wrapped.name, "args": {"query": "서울"}, "id": "c1"}]
    )
    # 최종 응답을 content-block 리스트로 — 실 모델 스트리밍 형태.
    ai_final = AIMessage(content=[{"type": "text", "text": FINAL}])
    graph = create_react_agent(
        ScriptedModel([ai_call, ai_final]), tools=[wrapped], checkpointer=MemorySaver()
    )
    acc: list[str] = []
    async for stream_mode, chunk in graph.astream(
        {"messages": [{"role": "user", "content": "서울 날씨"}]},
        config={"configurable": {"thread_id": "v92b"}},
        stream_mode=["messages", "updates"],
    ):
        if stream_mode != "messages":
            continue
        msg_chunk, _meta = chunk
        if runtime.is_tool_message(msg_chunk):
            continue
        text = runtime._content_text(getattr(msg_chunk, "content", ""))
        if text:
            acc.append(text)
    body = "".join(acc)  # 정규화 없으면 list가 섞여 TypeError
    check(FINAL in body, "list content 최종도 본문에 보존(크래시 없이)")
    check(RAW not in body, "list content 턴서도 RAW 미노출")


asyncio.run(integration())
asyncio.run(integration_content_blocks())

print(f"\nverify_092: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
