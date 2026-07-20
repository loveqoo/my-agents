"""verify_410 — 사고 과정 표시(thinking display) 백엔드 단위(스펙 410).

서버·모델 불필요(결정적) — reasoning_content 추출과 **축 분리**(본문·acc 미포함)를 순수 검증.

  U1 ReasoningChatOpenAI._create_chat_result: raw 응답의 reasoning_content를 additional_kwargs로
     되살린다(base는 버림). 사고 없는 응답엔 무영향.
  U2 스트리밍 훅: delta.reasoning_content → additional_kwargs(포워드 호환).
  U3 축 분리: _stream_reasoning는 reasoning만, _stream_text는 content만(reasoning 불포함 — acc 오염 0).

실행: uv run --project packages/api python tests/verify_410_thinking_display.py
"""

import os
import sys

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


def main() -> None:
    from agent.model import build_chat_openai

    client = build_chat_openai({"base_url": "http://x/v1", "api_key": "k", "model_id": "m"})
    check(type(client).__name__ == "ReasoningChatOpenAI", "U0 build_chat_openai가 ReasoningChatOpenAI 사용")

    # U1 비스트리밍: reasoning_content 있는 응답 → additional_kwargs로 되살림.
    resp = {
        "id": "x",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "13은 소수입니다.", "reasoning_content": "13을 2~3으로 나눠본다..."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    result = client._create_chat_result(resp)
    msg = result.generations[0].message
    check(
        msg.additional_kwargs.get("reasoning_content") == "13을 2~3으로 나눠본다...",
        f"U1a reasoning_content 추출 (got {msg.additional_kwargs.get('reasoning_content')!r})",
    )
    check(msg.content == "13은 소수입니다.", "U1b 본문(content)은 그대로")

    # U1c 사고 없는 응답엔 reasoning_content 키 없음(무영향).
    resp2 = {"id": "y", "model": "m", "choices": [{"index": 0, "message": {"role": "assistant", "content": "4"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    r2 = client._create_chat_result(resp2)
    check("reasoning_content" not in r2.generations[0].message.additional_kwargs, "U1c 사고 없으면 키 부재(무영향)")

    # U2 스트리밍 훅: delta.reasoning_content → additional_kwargs.
    from langchain_core.messages import AIMessageChunk

    chunk = {"choices": [{"index": 0, "delta": {"content": "부분", "reasoning_content": "생각조각"}, "finish_reason": None}]}
    gen = client._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})
    check(
        gen is not None and gen.message.additional_kwargs.get("reasoning_content") == "생각조각",
        f"U2 스트리밍 델타 reasoning 추출 (got {getattr(gen and gen.message, 'additional_kwargs', {})})",
    )

    # U3 축 분리: _stream_reasoning=reasoning만, _stream_text=content만(reasoning 불포함).
    from api.chat_sse_frames import _stream_reasoning, _stream_text

    m = AIMessageChunk(content="답변 본문", additional_kwargs={"reasoning_content": "사고 과정"})
    check(_stream_reasoning(m) == "사고 과정", f"U3a _stream_reasoning=reasoning (got {_stream_reasoning(m)!r})")
    check(_stream_text(m) == "답변 본문", f"U3b _stream_text=content만 (got {_stream_text(m)!r})")
    check("사고" not in _stream_text(m), "U3c 본문 추출에 reasoning 안 섞임(acc 오염 0 — 축 분리)")
    # 사고 없는 메시지: reasoning 프레임 없음.
    m2 = AIMessageChunk(content="그냥 답")
    check(_stream_reasoning(m2) == "", "U3d 사고 없으면 reasoning 빈 문자열(프레임 없음)")

    # U4 영속 관문 정화(codex 410 P1) — 파서 없는 서버가 <think>를 content에 인라인해도 영속 본문엔 0.
    from api.chat_sse_frames import strip_reasoning_blocks

    check(
        strip_reasoning_blocks("<think>속으로 계산</think>답은 4입니다.") == "답은 4입니다.",
        f"U4a 종결 <think> 블록 제거 (got {strip_reasoning_blocks('<think>속으로 계산</think>답은 4입니다.')!r})",
    )
    check(
        strip_reasoning_blocks("답 시작 <think>미종결 사고 스트림 절단") == "답 시작 ",
        "U4b 미종결 <think>(스트림 절단) 이후 제거",
    )
    check(strip_reasoning_blocks("사고 없는 순수 답변") == "사고 없는 순수 답변", "U4c 사고 없으면 무변화(통과)")
    check(
        strip_reasoning_blocks("<think>a</think>본문<think>b</think>끝") == "본문끝",
        "U4d 다중 블록 제거",
    )
    check(
        "사고" not in strip_reasoning_blocks("<think>은밀한 사고</think>공개 답변"),
        "U4e 정화 후 본문에 사고 흔적 0(영속 불변식)",
    )

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)
    print("VERIFY410_OK")


if __name__ == "__main__":
    main()
