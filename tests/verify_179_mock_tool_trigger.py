"""스펙 179 검증 — mock 모델 개발용 도구 트리거(HIL 승인 실습 enabler).

  T1 트리거 매치: tools=[delete_record] + "r1 삭제" → tool_call(name·record_id 채움), 비스트림.
  T2 무회귀(도구 미바인딩): tools 없음 → 평문(finish_reason stop).
  T3 무회귀(트리거 무매치): tools 있으나 키워드 없음 → 평문.
  T4 재개 후 턴: messages에 role=tool 있으면 → 평문(무한 tool_call 루프 차단).
  T5 스트림 계약: stream=true 트리거 → tool_calls delta + finish_reason "tool_calls".
  T6 id 추출: 다양한 식별자(rec-001·42) 정확 추출, 없으면 기본값.

실행: cd packages/api && uv run python ../../tests/verify_179_mock_tool_trigger.py
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import mock_remote as MR  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


_DELETE_TOOL = {"type": "function", "function": {"name": "delete_record",
                "parameters": {"type": "object", "properties": {"record_id": {"type": "string"}}}}}


def _body(user_text, tools=None, extra_msgs=None, stream=False):
    msgs = [{"role": "user", "content": user_text}]
    if extra_msgs:
        msgs = extra_msgs + msgs
    b = {"messages": msgs, "model": "mock-chat"}
    if tools is not None:
        b["tools"] = tools
    if stream:
        b["stream"] = True
    return b


async def _collect_stream(resp) -> str:
    out = []
    async for chunk in resp.body_iterator:
        out.append(chunk if isinstance(chunk, str) else chunk.decode())
    return "".join(out)


async def main() -> None:
    # T1 트리거 매치 → tool_call
    r = await MR.remote_v1_chat_completions(_body("레코드 r1 삭제해줘", tools=[_DELETE_TOOL]))
    choice = r["choices"][0]
    tcs = choice["message"].get("tool_calls") or []
    check(choice["finish_reason"] == "tool_calls" and len(tcs) == 1, "T1 트리거 → finish=tool_calls, 1개")
    check(tcs and tcs[0]["function"]["name"] == "delete_record", "T1 도구명 delete_record")
    args = json.loads(tcs[0]["function"]["arguments"]) if tcs else {}
    check(args.get("record_id") == "r1", f"T1 record_id 추출='r1' (got {args.get('record_id')})")

    # T2 도구 미바인딩 → 평문
    r = await MR.remote_v1_chat_completions(_body("레코드 r1 삭제해줘"))
    check(r["choices"][0]["finish_reason"] == "stop" and r["choices"][0]["message"].get("content"),
          "T2 도구 미바인딩 → 평문(stop)")

    # T3 트리거 무매치 → 평문
    r = await MR.remote_v1_chat_completions(_body("안녕 오늘 날씨 어때?", tools=[_DELETE_TOOL]))
    check(r["choices"][0]["finish_reason"] == "stop", "T3 트리거 무매치 → 평문(stop)")

    # T4 재개 후 턴(role=tool 존재) → 평문
    prior = [
        {"role": "user", "content": "r1 삭제"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_x", "type": "function", "function": {"name": "delete_record", "arguments": "{}"}}]},
        {"role": "tool", "content": "삭제 완료"},
    ]
    b = {"messages": prior + [{"role": "user", "content": "r2 삭제해줘"}], "model": "mock-chat",
         "tools": [_DELETE_TOOL]}
    # 주: 마지막 user가 트리거지만, 히스토리에 role=tool 있으면 평문(재개 요약 턴 규칙)
    r = await MR.remote_v1_chat_completions(b)
    check(r["choices"][0]["finish_reason"] == "stop", "T4 히스토리에 tool 결과 → 평문(루프 차단)")

    # T5 스트림 계약
    resp = await MR.remote_v1_chat_completions(_body("r5 지워줘", tools=[_DELETE_TOOL], stream=True))
    body = await _collect_stream(resp)
    check("tool_calls" in body and '"finish_reason": "tool_calls"' in body,
          "T5 스트림 → tool_calls delta + finish tool_calls")
    check("delete_record" in body and "r5" in body, "T5 스트림에 도구명·record_id 포함")

    # T7 네임스페이스 도구명(그래프 바인딩 실제 형태 local-tools__delete_record)
    ns_tool = {"type": "function", "function": {"name": "local-tools__delete_record",
               "parameters": {"type": "object", "properties": {"record_id": {"type": "string"}}}}}
    r = await MR.remote_v1_chat_completions(_body("r7 삭제해줘", tools=[ns_tool]))
    tcs = r["choices"][0]["message"].get("tool_calls") or []
    check(tcs and tcs[0]["function"]["name"] == "local-tools__delete_record",
          f"T7 네임스페이스명으로 emit (got {tcs[0]['function']['name'] if tcs else None})")

    # T6 id 추출 다양성
    check(MR._extract_record_id("rec-001 지워") == "rec-001", "T6 rec-001 추출")
    check(MR._extract_record_id("42번 삭제") == "42", "T6 숫자 42 추출")
    check(MR._extract_record_id("아무 것도 없음") == "rec-001", "T6 없으면 기본값 rec-001")

    print()
    if _fails:
        print(f"검증 실패 {len(_fails)}건:")
        for f in _fails:
            print(f"  - {f}")
        sys.exit(1)
    print("스펙 179 mock 도구 트리거 — 전부 통과.")


if __name__ == "__main__":
    asyncio.run(main())
