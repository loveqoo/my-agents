"""원격(A2A) 에이전트 중계 — chat_stream.py에서 분할(스펙 392 P1, 순수 이동).

원격 A2A 중계(_a2a_stream, 스펙 057): 등록 카드 url로 JSON-RPC message/stream 호출 → 우리 SSE로
재전송. 파사드는 chat.py(재수출 계약).
"""

import json
import time
import uuid
from collections.abc import AsyncIterator

from . import a2a_client, runtime
from .chat_context import ChatContext
from .chat_persist import _mid_frame, _persist


async def _a2a_stream(ctx: ChatContext, user_text: str, user_id: str | None) -> AsyncIterator[str]:
    """원격(A2A) 에이전트: 등록된 카드 url로 JSON-RPC message/stream 호출 → 응답을 우리 SSE로 재전송.

    code(우리가 배포한 SDK)·external(제3자) 모두 이 경로를 탄다(스펙 057: A2A 단일화). 전송은
    a2a_client 계층이 담당(JSON-RPC message/stream|send).
    """
    yield f"data: {json.dumps({'session': ctx.session_id}, ensure_ascii=False)}\n\n"
    endpoint = ctx.endpoint
    if not endpoint:
        yield f"data: {json.dumps({'error': '외부 에이전트에 A2A 엔드포인트(url)가 없습니다'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
        return

    streaming = a2a_client.card_streaming(ctx.card)
    acc: list[str] = []
    errored = False
    t0 = time.perf_counter()
    # 세션 id를 A2A contextId로 — 호출당 단일 메시지지만 서버가 맥락을 잇게 한다(스펙 057, 멀티턴 보존).
    async for frame in a2a_client.a2a_stream(
        endpoint, ctx.token, user_text, streaming=streaming, context_id=ctx.session_id
    ):
        if "error" in frame:
            errored = True
            msg = frame["error"]
            # 텍스트가 한 줄도 안 온 채 에러로 끝나면(엔드포인트 미도달 류) raw 코드만 보여주지 않고
            # 행동가능 안내를 덧붙인다(스펙 081 P2). 부분 스트림 뒤 에러엔 미부가 — 그땐 도달은 됐다.
            if not acc:
                msg = f"{msg} — 엔드포인트에 도달하지 못했습니다. 재동기화(자가치유) 또는 재연결을 시도하세요."
            yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"
        elif frame.get("text"):
            acc.append(frame["text"])
            yield f"data: {json.dumps({'text': frame['text']}, ensure_ascii=False)}\n\n"

    full = "".join(acc)
    total_ms = int((time.perf_counter() - t0) * 1000)
    tokens = runtime.estimate_tokens(len(user_text), len(full))
    trace = {
        "latencyMs": total_ms,
        "tokens": tokens,
        "promptRef": ctx.ext_agent_id,
        "memories": [],
        "mcp": [],
        "graph": [
            {"node": "__start__", "ms": 0},
            {"node": "a2a_call", "ms": total_ms},
            {"node": "__end__", "ms": 0},
        ],
        "remote": True,
        "a2a": True,
    }
    if not errored and full.strip():  # 공백-only 응답은 영속하지 않음(적대리뷰 L1)
        # 원격(A2A)은 로컬 그래프 thread_id가 없어 턴 id를 여기서 생성(로컬 포맷 미러, 스펙 364) —
        # 원격 턴도 이력에서 turn_id로 묶이게(프롬프트 출처는 원격 측이라 미기록=null, chat_context 가드).
        turn_id = f"{ctx.ext_agent_id}:{ctx.session_id}:{uuid.uuid4().hex[:8]}"
        mid = await _persist(
            ctx,
            user_text,
            full,
            trace,
            tokens,
            ctx.persist_history,
            user_id=user_id,
            turn_id=turn_id,
        )
        yield _mid_frame(mid)  # 스펙 209 P1.5 — 피드백 부착용 assistant id
    yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"
