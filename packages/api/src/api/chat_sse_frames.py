"""SSE 스트림 sink·HIL/산출물 인터럽트 프레임 가족 — chat.py에서 분할(스펙 396 P3, 순수 이동).

가족별 계약이 다름을 보존(공통화 금지 — codex 396): ask/form=질문·폼을 assistant 메시지로
**영속하고** trace+done, approval=정상 턴 **영속 안 함**·Approval row+pending trace만.
파사드는 chat.py(재수출 계약).
"""

import json
import secrets
import time
from collections.abc import AsyncIterator

from langchain_core.messages import BaseMessage

from . import runtime
from .chat_approval import _PENDING_ARTIFACT, _create_approval
from .chat_context import ChatContext
from .chat_persist import _mid_frame, _persist
from .chat_trace import _broker_calls_trace, _overrides_trace
from .chat_turn_runtime import ChatTurnRuntime


def _stream_text(msg_chunk: BaseMessage) -> str:
    """messages 청크 → 표시 텍스트. 도구 원본 응답(ToolMessage)은 본문서 제외 — 표시·영속(acc)·메모리·
    토큰 일괄 정화(스펙 092; 도구 호출은 calls_sink trace에 독립 보존). content는 str이 아니라
    content-block 리스트일 수 있어(AIMessageChunk) _content_text로 str 보장 — 안 하면 acc 합치기
    (`"".join`)서 TypeError(092 codex P1)."""
    if runtime.is_tool_message(msg_chunk):
        return ""
    return runtime._content_text(getattr(msg_chunk, "content", ""))


def _ingest_update(
    chunk: dict, interrupts: list, observed: list, t_prev: float
) -> tuple[float, list[str]]:
    """updates 청크 처리 — interrupt 수집·노드 발화 기록(스펙 085/086). 반환 (t_prev, artifact_frames).

    한 업데이트가 다중 interrupt를 담을 수 있어(한 턴에 위험 도구 여러 개) 모두 모은다 — [0]만
    보면 나머지가 조용히 샌다. ms=직전 update 이후 경과(직렬 그래프=노드별 실측, 스펙 086 ①),
    summary=안전 요약(키기반 redaction + raw 캡, 086 ②). 같은 노드 재발화는 별도 레코드(재진입 보존).
    한 청크에 노드 2+ = 병렬 superstep → 공유 ms를 노드별 실측처럼 과장 말라(F4)."""
    if "__interrupt__" in chunk:
        interrupts.extend(i.value for i in chunk["__interrupt__"])
    now = time.perf_counter()
    ms = int((now - t_prev) * 1000)
    fired = [(n, d) for n, d in chunk.items() if not n.startswith("__")]
    is_parallel = len(fired) > 1
    frames: list[str] = []
    for node, delta in fired:
        rec = {
            "node": node,
            "ms": ms,
            "summary": runtime._summarize_node_update(node, delta),
        }
        if is_parallel:
            rec["parallel"] = True
        observed.append(rec)
        # 산출물형(스펙 188): produce가 커밋한 artifact를 프레임으로 노출. 요약 텍스트(AIMessage)는
        # "messages" 스트림이 이미 흘린다(노드 반환 메시지도 스트림됨 — 실측) → 여기선 artifact
        # 프레임만(중복 방지). 타 에이전트 무영향.
        if isinstance(delta, dict) and delta.get("artifact"):
            frames.append(
                f"data: {json.dumps({'artifact': delta['artifact']}, ensure_ascii=False)}\n\n"
            )
    if fired:
        t_prev = now
    return t_prev, frames


def _artifact_wait_trace(
    ctx: ChatContext,
    turn: ChatTurnRuntime,
    *,
    t0: float,
    tokens: dict,
    observed: list,
    sent_messages: list[dict],
    awaiting: dict,
) -> dict:
    """ask/form 대기 턴 trace 조립(스펙 188) — 실행 버전 표기(스펙 242) 포함. 인스펙터: 진행 중 표기."""
    return {
        "latencyMs": int((time.perf_counter() - t0) * 1000),
        "tokens": tokens,
        "promptRef": ctx.ext_agent_id,
        "memories": turn.mem_hits,
        "mcp": turn.calls_sink,
        "graph": observed,
        "artifact": awaiting,
        **(
            {
                "agentVersion": ctx.exec_version,
                **({"versionPinned": True} if ctx.pinned_version else {}),
            }
            if ctx.exec_version
            else {}
        ),
        "sentMessages": sent_messages,
    }


async def _ask_frames(
    ctx: ChatContext,
    interrupted: dict,
    turn: ChatTurnRuntime,
    *,
    thread_id: str,
    user_id: str | None,
    user_text: str,
    t0: float,
    messages: list[dict],
    sent_messages: list[dict],
    observed: list,
) -> AsyncIterator[str]:
    """산출물형 ask(스펙 188) — kind로 엄격 게이트(승인 interrupt에는 kind가 없음 → 기존 경로 무접촉).

    질문을 텍스트 프레임으로 내보내고, 이 thread를 세션 pending에 등록해 다음 사용자 입력이
    Command(resume=)로 재개하게 한다. ask 턴은 정상 대화 교환 — 질문을 assistant 메시지로 영속
    (승인 턴의 "영속 안 함"과 다름: 질문·답이 대화 이력에 남아야 한다)."""
    question = str(interrupted.get("text") or "").strip() or "(질문)"
    _PENDING_ARTIFACT[ctx.session_id] = {
        "thread_id": thread_id,
        "version": ctx.pinned_version,
    }
    yield f"data: {json.dumps({'text': question}, ensure_ascii=False)}\n\n"
    ask_tokens = runtime.estimate_tokens(sum(len(m["content"]) for m in messages), len(question))
    ask_trace = _artifact_wait_trace(
        ctx,
        turn,
        t0=t0,
        tokens=ask_tokens,
        observed=observed,
        sent_messages=sent_messages,
        awaiting={"awaiting": "ask"},
    )
    mid = await _persist(
        ctx,
        user_text,
        question,
        ask_trace,
        ask_tokens,
        ctx.persist_history,
        user_id=user_id,
        turn_id=thread_id,
    )
    yield _mid_frame(mid)  # 스펙 209 P1.5
    yield f"event: trace\ndata: {json.dumps(ask_trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


async def _form_frames(
    ctx: ChatContext,
    interrupted: dict,
    turn: ChatTurnRuntime,
    *,
    thread_id: str,
    user_id: str | None,
    user_text: str,
    t0: float,
    messages: list[dict],
    sent_messages: list[dict],
    observed: list,
) -> AsyncIterator[str]:
    """산출물형 form(스펙 188 P2) — 승인 프레임의 일반화. 필드 명세+프리필을 프레임으로 내보내고
    pending에 (thread, formId, fields)를 등록: 제출(body.form)이든 텍스트든 다음 입력이 재개한다."""
    form_id = "frm-" + secrets.token_hex(4)
    form_fields = interrupted.get("fields") or []
    _PENDING_ARTIFACT[ctx.session_id] = {
        "thread_id": thread_id,
        "kind": "form",
        "form_id": form_id,
        "fields": form_fields,
        "version": ctx.pinned_version,  # 재개 턴 버전 승계(codex 242 #1)
    }
    form_frame = {
        "form": {
            "fields": form_fields,
            "prefill": interrupted.get("prefill") or {},
            **({"note": interrupted["note"]} if interrupted.get("note") else {}),
        },
        "formId": form_id,
    }
    # 이력에는 폼 요약 한 줄(프레임 자체는 휘발) — 질문·답 흐름이 대화 기록에 남게.
    # 라이브 버블에도 같은 텍스트를 흘린다(세션 재로드 표시와 일치 — 빈 버블 방지).
    form_msg = "📋 입력이 필요합니다: " + ", ".join(
        str(f.get("label") or f.get("key") or "?") for f in form_fields
    )
    yield f"data: {json.dumps({'text': form_msg}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps(form_frame, ensure_ascii=False)}\n\n"
    form_tokens = runtime.estimate_tokens(sum(len(m["content"]) for m in messages), len(form_msg))
    form_trace = _artifact_wait_trace(
        ctx,
        turn,
        t0=t0,
        tokens=form_tokens,
        observed=observed,
        sent_messages=sent_messages,
        awaiting={"awaiting": "form", "formId": form_id},
    )
    mid = await _persist(
        ctx,
        user_text,
        form_msg,
        form_trace,
        form_tokens,
        ctx.persist_history,
        user_id=user_id,
        turn_id=thread_id,
    )
    yield _mid_frame(mid)  # 스펙 209 P1.5
    yield f"event: trace\ndata: {json.dumps(form_trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


def _pending_approval_trace(
    ctx: ChatContext,
    turn: ChatTurnRuntime,
    *,
    t0: float,
    apid: str,
    action: str,
    user_text: str,
    sent_messages: list[dict],
) -> dict:
    """승인 대기 턴 trace(스펙 041/079/130/131/134) — 일시정지 이전에 이미 실행된 관측을 표면화."""
    pending_trace = {
        "latencyMs": int((time.perf_counter() - t0) * 1000),
        "tokens": {"in": 0, "out": 0},
        "promptRef": ctx.ext_agent_id,
        "memories": turn.mem_hits,
        "mcp": turn.calls_sink,
        "graph": [],
        "approval": {"id": apid, "action": action, "status": "pending"},
        **({"agentVersion": ctx.exec_version} if ctx.exec_version else {}),
    }
    # 승인대기 턴도 회상 조회 이력 일관 노출(스펙 079).
    if turn.used_memory:
        pending_trace["memoryQuery"] = (
            user_text if ctx.memory_user_text is None else ctx.memory_user_text
        )[:300]
    if turn.broker.invocations:
        # 일시정지 **이전에 이미 실행된** 선행 브로커 호출 표면화(스펙 130, codex #2).
        pending_trace["brokerCalls"] = _broker_calls_trace(turn.broker.invocations)
    if turn.history_windows:
        # 일시정지 이전 carry 노드가 이미 기록한 단기 기억 창 표면화(codex 270 Low — 관측 일관).
        pending_trace["historyWindows"] = turn.history_windows
    pending_trace["sentMessages"] = sent_messages  # 승인대기 턴도 전송 전문(스펙 131)
    ov_trace_p = _overrides_trace(ctx.overrides, ctx.overrides_nodes_status)
    if ov_trace_p:
        pending_trace["overrides"] = ov_trace_p  # 스펙 134
    if ctx.rag_collections:
        pending_trace["ragCollections"] = [c["name"] for c in ctx.rag_collections]
    return pending_trace


async def _approval_frames(
    ctx: ChatContext,
    interrupted: dict,
    turn: ChatTurnRuntime,
    *,
    thread_id: str,
    user_id: str | None,
    user_text: str,
    t0: float,
    sent_messages: list[dict],
) -> AsyncIterator[str]:
    """위험 도구가 그래프를 멈췄다 → 런타임 Approval 생성 + "대기" 프레임 후 종료(정상 턴 영속 안 함).
    부수효과(canned·calls_sink)는 interrupt 이전이라 0 — 승인 전 무실행 불변식(스펙 041 §3.3)."""
    if ctx.pinned_version:
        # 버전 미리보기(스펙 242) — 승인 재개는 서빙 config로 돌아 버전이 어긋난다(drift).
        # Approval을 만들지 않고 명시 안내(235 비영속 게이트와 동형). 도구는 interrupt 이전이라 미실행.
        yield f"data: {json.dumps({'error': '버전 미리보기에서는 승인이 필요한 도구를 사용할 수 없습니다 — 활성 버전에서 실행하거나 승인 없는 도구를 사용하세요.'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
        return
    if ctx.ephemeral:
        # 비영속(스펙 237) — 승인 대기는 만들 수 없다: _create_approval이 세션+Approval 행을
        # 쓰고(235 "쓰기 0" 위반), 체크포인터도 없어 재개 불가. **실측 주의**: 체크포인터가
        # None이어도 interrupt 자체는 발생해 여기 도달한다(235의 "구조적 미도달" 가정은 틀렸다
        # — 이 게이트가 실제 봉합). 도구는 interrupt 이전이라 미실행(부수효과 0). 조용한 실패
        # 대신 명시 안내(회고 214).
        yield f"data: {json.dumps({'error': '비영속(1회성) 에이전트는 승인이 필요한 도구를 사용할 수 없습니다 — 승인·재개에는 기록(DB)이 필요합니다. 승인 없는 도구를 쓰거나 일반 에이전트를 사용하세요.'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
        return
    apid = await _create_approval(ctx, thread_id, interrupted, user_id)
    action = interrupted.get("action", "(작업)")
    # approver 반영(스펙 180) — self면 요청자 본인이 승인. 하드코딩 "관리자 승인"은 오표기였다.
    approver = interrupted.get("approver")
    kind_label = "본인 승인" if approver == "self" else "관리자 승인"
    wait_msg = f"⏸ 승인 대기: {action} — {kind_label}이 필요합니다. (승인 큐 {apid})"
    yield f"data: {json.dumps({'text': wait_msg, 'approval': apid, 'approver': approver}, ensure_ascii=False)}\n\n"
    pending_trace = _pending_approval_trace(
        ctx, turn, t0=t0, apid=apid, action=action, user_text=user_text, sent_messages=sent_messages
    )
    yield f"event: trace\ndata: {json.dumps(pending_trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


async def _interrupt_frames(
    ctx: ChatContext,
    interrupts: list[dict],
    turn: ChatTurnRuntime,
    *,
    thread_id: str,
    user_id: str | None,
    user_text: str,
    t0: float,
    messages: list[dict],
    sent_messages: list[dict],
    observed: list,
) -> AsyncIterator[str]:
    """interrupt 종결 프레임 디스패치 — 다중=fail-closed, ask/form=산출물 대기, 그 외=승인 대기.

    한 턴에 위험 도구가 둘 이상 호출되면(다중 pending interrupt) 현재 재개 프로토콜은 **단일
    interrupt만** 지원한다 — Command(resume=)에 interrupt id를 안 주므로 langgraph가 "must
    specify interrupt id"로 실패하고, except가 삼켜 status=approved인데 도구는 영영 미실행으로
    멈춘다(적대 검증 Finding 1). 다중을 무시하고 하나만 Approval로 만들면 오도하는 approved row가
    남는다. 그래서 다중은 **승인 row를 만들지 않고** 명시적 에러로 닫는다(fail-closed·정직:
    부수효과 미실행 유지). 사용자는 한 번에 하나씩 재시도. 다중 동시 게이트는 §7 빚."""
    if len(interrupts) > 1:
        yield f"data: {json.dumps({'error': '한 턴에 승인이 필요한 위험 도구가 둘 이상 호출되었습니다. 하나씩 다시 시도해 주세요.'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
        return
    interrupted = interrupts[0]
    kind = interrupted.get("kind")  # 산출물형만 kind 보유 — 승인 interrupt에는 없음(엄격 게이트)
    if kind == "ask":
        frames = _ask_frames(
            ctx,
            interrupted,
            turn,
            thread_id=thread_id,
            user_id=user_id,
            user_text=user_text,
            t0=t0,
            messages=messages,
            sent_messages=sent_messages,
            observed=observed,
        )
    elif kind == "form":
        frames = _form_frames(
            ctx,
            interrupted,
            turn,
            thread_id=thread_id,
            user_id=user_id,
            user_text=user_text,
            t0=t0,
            messages=messages,
            sent_messages=sent_messages,
            observed=observed,
        )
    else:
        frames = _approval_frames(
            ctx,
            interrupted,
            turn,
            thread_id=thread_id,
            user_id=user_id,
            user_text=user_text,
            t0=t0,
            sent_messages=sent_messages,
        )
    async for frame in frames:
        yield frame
