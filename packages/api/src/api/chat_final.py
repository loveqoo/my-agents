"""턴 종결·백그라운드 기억 저장 — chat.py에서 분할(스펙 396 P2). 스펙 314 계약의 정의 모듈.

계약(동결): 답변+trace+done을 먼저 흘려 '처리 중'을 즉시 해제, 무거운 자동 기억 저장은
detached task — **done을 yield하기 전에 태스크 생성**(done 직후 클라이언트가 끊어도 저장 보장,
verify_314가 직접 핀). memoryPending은 **라이브 trace 전용**(영속 trace 미포함 — 서버 재시작
시 스피너 영구 회전 차단). done 뒤 trailing `event: memory`로 pending 해제(프론트 api.ts 소비).
_final_frames(구 CC 13)는 태스크 스폰(_spawn_memory_task)·트레일링 프레임(_trailing_memory_frame)
추출로 분해. 파사드는 chat.py(재수출 계약).
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from agent.runtime import CustomAgent

from . import memory, trace_capture
from .chat_context import ChatContext
from .chat_persist import _mid_frame, _persist
from .chat_sse_frames import strip_reasoning_blocks
from .chat_trace import _final_trace, _finalize_memory_trace, _summarize_saved
from .chat_turn_runtime import ChatTurnRuntime

log = logging.getLogger("api.chat")

# 백그라운드 자동 기억 저장 태스크 참조(스펙 314) — 스트림(제너레이터)이 끝나거나 클라이언트가 떠나도
# 태스크가 GC/취소되지 않도록 강참조를 유지. 완료 시 콜백으로 스스로 제거한다.
_BG_MEMORY_TASKS: set[asyncio.Task] = set()
_MEMORY_ADD_TIMEOUT_S = (
    30  # 백그라운드 저장(mem0 LLM 추출) 대기 상한 — 초과 시 pending만 해제(codex P1)
)
_TRAILING_EVENT_TIMEOUT_S = (
    60  # 트레일링 이벤트 대기 상한 — 연결 무한 보유 방지(태스크는 계속, codex P1)
)


async def _bg_memory_add(
    add_scope: dict, user_text: str, full: str, mem_cfg: dict | None, mid: str | None
) -> dict:
    """백그라운드 자동 기억 저장(스펙 314) — done 이후 실행. **자기완결**(예외 삼킴): 저장→요약→영속
    trace 갱신을 모두 여기서 끝내, 클라이언트가 떠나도 저장·영속이 보장된다. 반환=요약(트레일링
    이벤트용). 자동 add scope는 user_id+run_id만(agent_id 미포함 — 누출 차단, 스펙 029/020).
    mem0 저장이 비정상적으로 오래 걸리면 상한(_MEMORY_ADD_TIMEOUT_S)에서 손을 떼고 error 요약으로
    마감한다(codex P1 — 무한 hang 시 pending이 안 풀리는 걸 방지; 스레드는 유실되나 드묾)."""
    try:
        saved = await asyncio.wait_for(
            asyncio.to_thread(
                memory.add,
                add_scope,
                [{"role": "user", "content": user_text}, {"role": "assistant", "content": full}],
                mem_cfg,
            ),
            timeout=_MEMORY_ADD_TIMEOUT_S,
        )
        summary = _summarize_saved(saved)
    except TimeoutError:
        log.warning("자동 기억 저장 시간 초과(백그라운드 %ss)", _MEMORY_ADD_TIMEOUT_S)
        summary = {"status": "error", "count": 0, "items": []}
    except Exception:
        log.exception("백그라운드 자동 기억 저장 실패")
        summary = {"status": "error", "count": 0, "items": []}
    if mid:
        try:
            await _finalize_memory_trace(mid, summary)
        except Exception:
            log.exception("영속 trace 기억 갱신 실패")
    return summary


def _memory_kickoff(
    turn: "ChatTurnRuntime",
    ctx: "ChatContext",
    user_text: str,
    full: str,
    mid: str | None,
    will_add_memory: bool,
    trace: dict,
) -> tuple["asyncio.Task | None", dict]:
    """저장 태스크 스폰+라이브 trace 결정(스펙 396 분해) — 반환 (task, live_trace).

    memoryPending은 **라이브 스트림에만**·**mid 있을 때만** 싣는다 — mid 없으면(persistHistory=false)
    완료 이벤트로 조용히 해제할 방법이 없어(mid로 패치) 스피너가 안 풀린다(codex P1)."""
    if not will_add_memory:
        return None, trace
    # 자동 기억 저장도 원발화만(스펙 407) — 첨부 문서 3만자가 유저 기억에 섞이지 않게.
    task = _spawn_memory_task(
        turn.add_scope,
        user_text if ctx.memory_user_text is None else ctx.memory_user_text,
        full,
        ctx.mem_cfg,
        mid,
    )
    return task, ({**trace, "memoryPending": True} if mid else trace)


def _spawn_memory_task(
    add_scope: dict, user_text: str, full: str, mem_cfg: dict | None, mid: str | None
) -> asyncio.Task:
    """저장 태스크 생성·등록(스펙 314) — done yield **전**에 호출된다(codex P0: yield 뒤에 만들면
    done 직후 취소 시 태스크 자체가 안 생겨 저장 유실). 강참조 유지, 완료 콜백이 스스로 제거."""
    task = asyncio.ensure_future(_bg_memory_add(add_scope, user_text, full, mem_cfg, mid))
    _BG_MEMORY_TASKS.add(task)  # 강참조 유지(GC/취소 방지) — 완료 콜백이 스스로 제거
    task.add_done_callback(_BG_MEMORY_TASKS.discard)
    return task


async def _trailing_memory_frame(task: asyncio.Task, mid: str) -> str | None:
    """done 뒤 트레일링 memory 이벤트(스펙 314) — 완료를 기다려 조용히 알린다(status 무관 —
    none/error도 pending 해제용). shield로 클라이언트 취소로부터 태스크를 보호하고, wait_for로
    대기 상한을 둬 저장이 비정상적으로 오래 걸려도 연결을 무한정 붙들지 않는다(codex P1 —
    태스크는 계속 완료돼 영속 trace를 갱신하므로 새로고침 시 반영). 취소(클라이언트 이탈)는
    재전파해 제너레이터를 정리한다. 반환 None=이벤트 생략(태스크·영속은 계속)."""
    try:
        summary = await asyncio.wait_for(asyncio.shield(task), timeout=_TRAILING_EVENT_TIMEOUT_S)
    except asyncio.CancelledError:
        raise
    except Exception:  # TimeoutError 포함 — 트레일링 이벤트만 생략(태스크·영속은 계속)
        return None
    return (
        "event: memory\n"
        f"data: {json.dumps({'mid': str(mid), 'memorySaved': summary}, ensure_ascii=False)}\n\n"
    )


async def _final_frames(
    ctx: ChatContext,
    turn: ChatTurnRuntime,
    *,
    errored: bool,
    acc: list[str],
    t0: float,
    capture: trace_capture.TraceCaptureHandler,
    messages: list[dict],
    sent_messages: list[dict],
    observed: list,
    impl: CustomAgent,
    user_text: str,
    user_id: str | None,
    history_restore: dict | None,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """턴 종결 — 브로커 서브스텝 합류·trace 조립·영속·자동 기억·trace/done 프레임."""
    # 브로커 서브스텝 호출을 관측 타임라인에 합류(스펙 100/101 설계결정 7 — broker.invoke가
    # invisible하지 않게). delegate 노드 update와 별개로 cap별 broker_invoke:<kind>:<...> 노드를
    # 남긴다(A2A는 broker_invoke:agent:*, MCP는 broker_invoke:mcp:<server>/<tool>). 위임이 없던
    # 턴은 invocations가 비어 무영향(무회귀).
    for inv in turn.broker.invocations:
        observed.append({"node": inv["node"], "ms": inv.get("ms", 0)})
    # 영속 본문 정화(스펙 410 P1) — reasoning 파서 없는 서버가 <think>를 content에 인라인해도
    # 영속·메모리·trace에 사고가 안 남게(축 분리 불변식은 서버 종류와 무관하게 성립해야 한다).
    full = strip_reasoning_blocks("".join(acc))
    total_ms = int((time.perf_counter() - t0) * 1000)
    # 오류 턴은 영속/메모리 저장하지 않는다 (부분/실패 응답 오염 방지).
    will_add_memory = (not errored) and turn.used_memory and bool(full)
    trace, tokens = _final_trace(
        ctx,
        turn,
        capture=capture,
        full=full,
        total_ms=total_ms,
        messages=messages,
        sent_messages=sent_messages,
        observed=observed,
        impl=impl,
        user_text=user_text,
        history_restore=history_restore,
    )
    # 영속되는 trace에는 memoryPending을 넣지 않는다(codex P1) — 저장을 완료 못 하면(서버 재시작·hang)
    # 영속 pending이 남아 새로고침 스피너가 영영 도는 걸 원천 차단. pending은 라이브 스트림에만 싣는다.
    mid = None
    if not errored:
        mid = await _persist(
            ctx,
            user_text,
            full,
            trace,
            tokens,
            ctx.persist_history,
            user_id=user_id,
            turn_id=thread_id,
        )
    if mid:
        yield _mid_frame(mid)  # 스펙 209 P1.5 — 피드백 부착용 assistant id
    # P0(codex): 저장 태스크를 done을 yield하기 **전에** 띄운다(_memory_kickoff) — done 직후
    # 클라이언트가 끊어(제너레이터 취소) yield 이후 코드가 재개되지 않아도, 태스크는 이미 생성·
    # 등록·detached라 끝까지 완료된다(저장·영속 보장).
    task, live_trace = _memory_kickoff(turn, ctx, user_text, full, mid, will_add_memory, trace)
    # 스펙 314: 답변+trace+done을 **먼저** 흘려 '처리 중'을 즉시 해제한다. 무거운 자동 기억 저장(mem0 LLM
    # 추출 — 초 단위)은 위 백그라운드 태스크가 담당. 이게 done 앞을 막던 게 지연의 원인이었다.
    yield f"event: trace\ndata: {json.dumps(live_trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"
    if task is not None and mid:
        frame = await _trailing_memory_frame(task, mid)
        if frame is not None:
            yield frame
