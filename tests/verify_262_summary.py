"""verify_262 (단위) — 인스펙터 노드 요약: clean 노드 remove를 사람 말로 (스펙 262).

  S1 격리 접기: RemoveMessage 2개+human+ai 델타 → "이전 맥락 2개 정리 (격리)" 포함·"remove" 미포함·
     실제 발화(user/assistant) 프리뷰 유지.
  S2 무회귀: remove 없는 델타는 기존 동작(user/assistant 프리뷰, 격리 노트 없음).
  S3 remove만: RemoveMessage만 있는 델타 → 격리 노트만·extra 없음.
  S4 비밀 불변식(086): 안전하지 않은 키의 문자열 값은 길이만(원문 미표시).

실행: uv run --project packages/api python tests/verify_262_summary.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage  # noqa: E402

from api.runtime import _summarize_node_update  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)


def main():
    rm = lambda i: RemoveMessage(id=f"m{i}")

    # S1 격리 접기
    s = _summarize_node_update("요약", {"messages": [rm(1), rm(2), HumanMessage(content="앞 결과"), AIMessage(content="요약 출력")]})
    check("이전 맥락 2개 정리 (격리)" in s, f"S1 격리 노트 표시 (got {s})")
    check("remove" not in s, f"S1 'remove' 내부어 미노출 (got {s})")
    check("user: «앞 결과»" in s and "assistant: «요약 출력»" in s, f"S1 실제 발화 프리뷰 유지 (got {s})")

    # S2 무회귀 — remove 없는 델타
    s2 = _summarize_node_update("분석", {"messages": [HumanMessage(content="입력"), AIMessage(content="분석 결과")]})
    check("격리" not in s2 and "user: «입력»" in s2 and "assistant: «분석 결과»" in s2, f"S2 무회귀(격리 노트 없음) (got {s2})")

    # S3 remove만
    s3 = _summarize_node_update("요약", {"messages": [rm(1), rm(2), rm(3)]})
    check("이전 맥락 3개 정리 (격리)" in s3 and "remove" not in s3 and "+" not in s3, f"S3 remove만(노트만, extra 없음) (got {s3})")

    # S4 비밀 불변식(086) — 임의(비안전·비민감) 키의 문자열 값은 원문 미표시, 길이만
    s4 = _summarize_node_update("x", {"custompayload": "verysecretvalue"})
    check("verysecretvalue" not in s4 and "<15자>" in s4, f"S4 임의 키 값 원문 미표시(길이만) (got {s4})")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
