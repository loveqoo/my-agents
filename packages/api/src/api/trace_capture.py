"""인스펙터 표시용 실측 캡처 (스펙 205) — 모델 호출 메시지·토큰 usage.

기존 인스펙터의 '전송 프롬프트'는 플랫폼 재구성(_build_sent_messages, 스펙 131)이라 커스텀 impl이
노드 안에서 만든 프롬프트(계획·도구 안내)와 어긋났고, 토큰은 글자수÷4 추정이었다. 이 핸들러는
그래프 실행 config.callbacks에 붙어 **모델에 실제로 간 것**을 관측한다:
- on_chat_model_start: 각 모델 호출의 메시지 배열(raw — 마스킹·캡은 소비자 chat.py가 적용).
- on_llm_end: usage_metadata(입·출력 토큰) 합산. 모델이 usage를 안 주면 usage_seen=False로 남아
  소비자가 추정 폴백(estimated=True 표기).

Langfuse 계측(스펙 118)과 별개 핸들러 — 그쪽은 무변경.
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


def _role_of(m: Any) -> str:
    t = getattr(m, "type", "") or ""
    return {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}.get(
        t, t or "unknown"
    )


def _content_of(m: Any) -> str:
    c = getattr(m, "content", "")
    text = c if isinstance(c, str) else str(c)
    # AIMessage가 본문 없이 tool_calls만 실은 경우 — 빈 문자열 대신 호출 의도를 표기(정직성).
    calls = getattr(m, "tool_calls", None)
    if calls and not text.strip():
        names = ", ".join(str(tc.get("name", "?")) for tc in calls)
        return f"(도구 호출: {names})"
    return text


class TraceCaptureHandler(BaseCallbackHandler):
    """한 턴(그래프 실행) 동안의 모델 호출 실측 — chat.py가 턴마다 새로 만들어 붙인다."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []  # 호출별 [{role, content}] (raw)
        self.tokens_in = 0
        self.tokens_out = 0
        self.usage_seen = False

    # langchain은 async 실행에서도 sync 핸들러를 호출해 준다(내부 래핑).
    def on_chat_model_start(self, _serialized: Any, messages: list, **_kwargs: Any) -> None:
        try:
            batch = messages[0] if messages else []
            self.calls.append([{"role": _role_of(m), "content": _content_of(m)} for m in batch])
        except Exception:
            pass

    def on_llm_end(self, response: Any, **_kwargs: Any) -> None:
        try:
            for gens in getattr(response, "generations", []) or []:
                for g in gens:
                    um = getattr(getattr(g, "message", None), "usage_metadata", None)
                    if um:
                        self.tokens_in += int(um.get("input_tokens", 0) or 0)
                        self.tokens_out += int(um.get("output_tokens", 0) or 0)
                        self.usage_seen = True
        except Exception:
            pass
