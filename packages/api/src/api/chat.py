"""등록된 에이전트와의 대화 (SSE 스트리밍).

prompt + (선택)mem0 장기 메모리 + (선택)MCP 합성 툴을 LangGraph로 합성해 실행하고,
세션/메시지/트레이스를 영속화한다. 트레이스는 Playground 인스펙터가 소비.

지배 스펙: docs/spec/007-real-agent-service.md (Phase 2)

스펙 291(Phase 3b) → 396: 관심사별 형제 모듈(chat_context/history/persist/trace/approval +
392: sse_errors/a2a_proxy/a2a_serve/graph_build + 396: turn_runtime/sse_frames/final)로 분할 —
이 모듈은 **파사드**(전 심볼 재수출) + 라우터 + `chat()` 진입 오케스트레이터만 갖는다.
외부의 `from api.chat import X` / `from api import chat` 접근은 전부 무변경(재배선 없는 분할 계약).
"""

import asyncio  # noqa: F401  (파사드 재수출 — 분할 전 공개 표면 보존)
import json
import logging
import secrets  # noqa: F401  (파사드 재수출)
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any  # noqa: F401  (파사드 재수출)

from fastapi import APIRouter, Depends, HTTPException

# ── 파사드 재수출(스펙 291) — 분할 전 chat.py의 공개 표면 전량 보존(외부 import 무변경) ──
from fastapi.responses import StreamingResponse
from langchain_core.messages import (  # noqa: F401
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.types import Command  # noqa: F401
from sqlalchemy import select  # noqa: F401
from sqlalchemy.exc import IntegrityError  # noqa: F401
from sqlalchemy.orm import selectinload  # noqa: F401

from agent.runtime import (
    AgentBuildContext,  # noqa: F401
    AgentConfigError,
    CustomAgent,  # noqa: F401
    is_remote_source,  # noqa: F401  (파사드 재수출 — 분할 전 공개 표면 보존)
)

from . import (  # noqa: F401
    a2a_client,
    authz,
    checkpoint_retention,
    checkpointer,
    crypto,
    memory,
    observability,
    runtime,
    trace_capture,
)
from .auth import current_principal, resolve_memory_user_id
from .broker import PolicyScopedBroker, build_broker  # noqa: F401
from .chat_a2a_proxy import _a2a_stream
from .chat_a2a_serve import (  # noqa: F401
    LocalServeTurn,
    ServeApprovalRequired,
    ServeCompleted,
    ServeFailed,
    ServeOutcome,
    prepare_serve_turn,
)
from .chat_approval import (  # noqa: F401
    _PENDING_ARTIFACT,
    _build_resume_broker,
    _create_approval,
    _impl_drifted,
    resume_approval,
)
from .chat_context import (  # noqa: F401
    _NODE_OVERRIDE_FIELDS,
    ChatContext,
    _is_remote,
    _load_context,
    _merge_node_overrides,
    _resolve_node_models,
    derive_pipeline_pool,
    resolve_agent_mem_cfg,
)
from .chat_final import (  # noqa: F401
    _BG_MEMORY_TASKS,
    _MEMORY_ADD_TIMEOUT_S,
    _TRAILING_EVENT_TIMEOUT_S,
    _bg_memory_add,
    _final_frames,
)
from .chat_graph_build import (  # noqa: F401
    _graph_fingerprint,
    _MemoryRecallProxy,
    _rag_tools_for,
    resolve_agent_runtime,
)
from .chat_history import (  # noqa: F401
    _SENT_MSG_CHAR_CAP,
    _SENT_MSG_COUNT_CAP,
    _build_sent_messages,
    _format_sent_measured,
    _history_load_limit,
    _HistoryWindowProxy,
    _load_session_conversation,
    _to_base_messages,
    _window,
)
from .chat_persist import _mid_frame, _persist, _resolve_session_for_persist  # noqa: F401
from .chat_sse_errors import (  # noqa: F401
    _CONN_ERR_MARKERS,
    _config_error_stream,
    _model_error_hint,
)
from .chat_sse_frames import (  # noqa: F401
    _approval_frames,
    _artifact_wait_trace,
    _ask_frames,
    _form_frames,
    _ingest_update,
    _interrupt_frames,
    _pending_approval_trace,
    _stream_text,
)
from .chat_trace import (  # noqa: F401
    _MEMORY_SAVE_ITEM_CAP,
    _MEMORY_SAVE_TEXT_CAP,
    _OVERRIDE_TRACE_KEYS,
    _annotate_context_sources,
    _annotate_execution,
    _annotate_memory_observations,
    _broker_calls_trace,
    _final_trace,
    _finalize_memory_trace,
    _overrides_trace,
    _summarize_saved,
)
from .chat_turn_runtime import (  # noqa: F401
    _GRAPH_CACHE,
    _GRAPH_CACHE_MAX,
    ChatTurnRuntime,
    _build_turn_runtime,
    _memory_inputs,
    _resolve_graph_entry,
    _seed_and_sent,
    _turn_config,
    graph_cache_stats,
)
from .db import SessionLocal
from .mem_config import (  # noqa: F401
    _build_mem_cfg,
    _default_chat_model,
    _default_embed_model,
)
from .models import (  # noqa: F401
    Agent,
    Approval,
    Collection,
    McpServer,
    Message,
    ModelConfig,
    Session,
    User,
)
from .ownership import next_owner  # noqa: F401
from .references import config_names  # noqa: F401
from .schemas import ChatRequest

router: APIRouter = APIRouter(prefix="/agents", tags=["chat"])
log = logging.getLogger("api.chat")


# 스펙 396: 턴 런타임(캐시 포함)→chat_turn_runtime, 프레임 가족→chat_sse_frames, 종결·기억→chat_final로
# 하강(위 파사드 재수출로 외부 표면 무변경). 이 파일=파사드+라우터+진입 헬퍼 2개+chat() 오케스트레이터.


# ---------------------------- chat() 진입 헬퍼 (스펙 291 분해) ----------------------------


async def _validate_entry(
    agent_id: uuid.UUID, body: ChatRequest, principal: User | str
) -> str | None:
    """채팅 진입 게이트 — 사용 권한(147)·버전 지정 권한(242)·재개 턴 버전 승계. 반환: 적용할 version."""
    # 사용 게이트(스펙 147): private 에이전트는 소유자·특권만 — 목록에서 안 보이는 존재이므로
    # 404-fold(068 — 403으로 존재를 알려주지 않는다).
    from .models import Agent as _AgentRow
    from .ownership import may_use_agent

    async with SessionLocal() as _s:
        arow = await _s.get(_AgentRow, agent_id)
    if arow is None or not may_use_agent(arow, principal):
        raise HTTPException(status_code=404, detail="agent not found")
    req_version = body.version
    if req_version is not None:
        # 버전 지정 실행은 관리 권한(codex 242 #2) — 초안은 미공개 작업본이라 "사용 권한만" 있는
        # 유저의 미리보기는 누출. 버전 목록 자체는 상세에 보이므로 403 명시(404-fold 불요).
        from .ownership import may_manage as _may_manage

        if not _may_manage(arow, principal):
            raise HTTPException(
                status_code=403, detail="버전 지정 실행은 이 에이전트를 관리할 수 있어야 합니다"
            )
    elif body.sessionId:
        # ask/form 재개 턴의 버전 승계(codex 242 #1) — 미리보기 턴이 만든 pending(체크포인트)은 그
        # 버전 config로만 재개해야 한다(활성 config로 재개하면 drift). 클라이언트가 재개 턴에 version을
        # 안 보내도 서버가 pending에 저장해 둔 버전을 이어받는다.
        pend = _PENDING_ARTIFACT.get(body.sessionId)
        if pend and pend.get("version"):
            req_version = pend["version"]
    return req_version


async def _prepare_conversation(
    ctx: ChatContext, body: ChatRequest
) -> tuple[list[dict], dict | None]:
    """히스토리 서버 재구성(스펙 289 P1) — 반환 (conversation, history_restore 실측).

    플랫폼 계약: "sessionId + 새 메시지"만 보내는 클라이언트는 서버가 영속 대화를 이어붙인다
    (에이전트 플랫폼 관행 — Assistants/A2A contextId류). 판정(auto): ① 재개에 성공한 소유 세션
    (session_pk 존재 — 타인/미존재 id는 해석이 새 세션으로 접어 재구성 대상이 없음, 068 열거 오라클
    보존) ② **body가 정확히 user 메시지 1개**. codex 289 #1~#3으로 조인 규칙: "assistant 부재"만
    보면 빈 배열·user-only 누적 클라·assistant 위조가 샌다 — "새 턴 1개"가 계약 그 자체.
    그 외 형태(누적 전송 등)=클라 관리 모드(플레이그라운드 무회귀). 캐시는 두지 않는다(스펙 289
    합의) — 조회를 필요 최대 depth로 LIMIT해 읽기량 상수 고정, 소요 ms를 trace.historyRestore로 실측."""
    conversation = [{"role": m.role, "content": m.content} for m in body.messages]
    history_restore: dict | None = None
    if ctx.session_pk is not None and len(body.messages) == 1 and body.messages[0].role == "user":
        t_hr = time.perf_counter()
        prior = await _load_session_conversation(
            ctx.session_id, ctx.agent_pk, limit=_history_load_limit(ctx)
        )
        if prior:
            conversation = prior + conversation
            history_restore = {
                "mode": "server",
                "restored": len(prior),
                "ms": int((time.perf_counter() - t_hr) * 1000),
            }
    return conversation, history_restore


@router.post("/{agent_id}/chat")
async def chat(
    agent_id: uuid.UUID, body: ChatRequest, principal: User | str = Depends(current_principal)
) -> StreamingResponse:
    # 스펙 068: resume 바인딩에 067과 *동일한* 소유자 스코프를 주입(정본 authz.own_scope 재사용, 298).
    # 비-admin이 타인/추측 session_id를 줘도 매칭 실패 → 새 세션(열거 오라클·소유권 탈취 봉인).
    own = authz.own_scope(principal, "sessions", "read")
    req_version = await _validate_entry(agent_id, body, principal)
    ctx = await _load_context(
        agent_id, body.sessionId, body.overrides, own=own, version=req_version
    )
    user_text = body.messages[-1].content if body.messages else ""

    # mem0 user_id 축 = 인증 주체에서 도출(스펙 032). 쿠키 유저면 안정 UUID(str(user.id)),
    # mem0 user 축 정체성(스펙 387) — 단일 관문: 머신 토큰만 body.userId 수용(위임 호출),
    # 쿠키 유저가 보내면 422(032 보안 보존). 미지정 시 기존 동작(쿠키=자기 id, 머신=세션 축만).
    user_id = resolve_memory_user_id(principal, body.userId)

    # 코드(SDK)·외부(A2A) 에이전트 모두 비로컬 — 등록된 카드 url로 A2A 런타임 호출(스펙 057: A2A 단일화).
    # code=우리가 SDK로 배포한 A2A(provenance 메타 보유), external=제3자 A2A. 전송은 _a2a_stream 하나.
    # (구 _remote_stream 자체 SSE·code 분기는 057에서 폐기 — 플랫폼 전제대로 SDK도 A2A를 말한다.)
    # in-process 런타임 구현 해석(스펙 085). None이면 원격(A2A 불투명) → 기존 fallback 그대로.
    # 선언한 impl이 미해결이면 AgentConfigError(스펙 089 교정3) → default로 만회 않고 설정 실패 통보.
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as e:
        return StreamingResponse(_config_error_stream(str(e)), media_type="text/event-stream")
    if impl is None:
        return StreamingResponse(
            _a2a_stream(ctx, user_text, user_id), media_type="text/event-stream"
        )

    conversation, history_restore = await _prepare_conversation(ctx, body)
    try:
        turn = await _build_turn_runtime(ctx, impl, principal, user_id, user_text, conversation)
    except AgentConfigError as e:
        # 그래프 조립 시점 설정 실패(스펙 317 — 코드 노드 impl 미등록 등)도 resolve 실패와 동일하게
        # 정직 통보(default 만회·조용한 스킵 금지, 089 패턴).
        return StreamingResponse(_config_error_stream(str(e)), media_type="text/event-stream")
    graph = turn.graph
    thread_id, graph_input, pending_artifact = _resolve_graph_entry(ctx, body, user_text)
    capture = trace_capture.TraceCaptureHandler()
    config = _turn_config(ctx, thread_id, user_id, capture, calls_sink=turn.calls_sink)
    messages, sent_messages, seed_messages = _seed_and_sent(
        conversation,
        ctx,
        turn.pipeline,
        turn.seed_system,  # 캐시 경로: 프롬프트+회상+discovery 힌트(비캐시=prompt_prompt 동일)
        system_in_seed=turn.prompt_in_messages,
    )

    # interrupt 수집 리스트를 **턴 스코프로 끌어올린다**(스펙 346, codex P1): 관문(아래 event_stream의
    # finally)이 "그래프가 멈춘 채인가"를 알아야 한다. 승인 행 커밋·폼 포인터 등록은 interrupt보다
    # **나중**이라, 그 사이 취소되면 핀이 아직 없다 — 이 리스트가 유일한 증거다.
    interrupts: list[dict] = []

    async def _run_turn() -> AsyncIterator[str]:
        t0 = time.perf_counter()
        yield f"data: {json.dumps({'session': ctx.session_id}, ensure_ascii=False)}\n\n"
        acc: list[str] = []
        errored = False
        # updates 발화 레코드 [{node, ms(실측), summary}] — 스펙 085(노드열) + 086(실측·요약).
        observed: list[dict] = []
        t_prev = t0
        try:
            # 멀티 stream_mode: "messages"=토큰 스트림(기존), "updates"=노드 업데이트에서 __interrupt__
            # 감지(위험 도구가 그래프를 멈춘 신호). probe로 검증한 형태.
            async for stream_mode, chunk in graph.astream(
                graph_input if graph_input is not None else {"messages": seed_messages},
                config=config,
                stream_mode=["messages", "updates"],
                # durability="exit"(스펙 346) — 슈퍼스텝마다 쓰지 않고 **그래프가 끝날 때만** 박는다.
                # 실측: 3노드 턴이 checkpoints 3행 → 1행. interrupt도 "끝남"이라 HIL 정지 상태는
                # 그대로 박히고 재개도 된다(probe로 실증 — 재개 결과 정확). 중간 크래시 시 그 턴의
                # 진행이 소실되지만, 턴은 어차피 처음부터 재시도라 잃을 게 없다.
                durability="exit",
            ):
                if stream_mode == "messages":
                    msg_chunk, _meta = chunk
                    text = _stream_text(msg_chunk)
                    if text:
                        acc.append(text)
                        yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                elif stream_mode == "updates" and isinstance(chunk, dict):
                    t_prev, artifact_frames = _ingest_update(chunk, interrupts, observed, t_prev)
                    for frame in artifact_frames:
                        yield frame
        except Exception as exc:  # 모델/툴 오류도 프레임으로 전달
            errored = True
            # 산출물형 재개 중 크래시면 pending을 **원복**한다(적대 검증 P1-3). pop은 재개 진입 시
            # 1회였고(_resolve_graph_entry), 체크포인트(interrupt 상태)는 재개 실패로 그대로 남아
            # 있으므로, 포인터를 되살려야 다음 요청이 같은 thread로 재시도할 수 있다(안 하면 in-flight
            # 폼/질문이 고아가 돼 새 스레드로 시작 — 진행 소실). 새 interrupt를 낸 정상 경로는 여기 안 옴.
            if pending_artifact is not None:
                _PENDING_ARTIFACT[ctx.session_id] = pending_artifact
            # 연결 실패로 보이면 'Mock LLM' 전환 힌트를 덧붙인다(스펙 058 G4). 그 외 오류는 원문 유지.
            hint = _model_error_hint(exc, ctx.model_cfg)
            msg = f"{exc}\n{hint}" if hint else str(exc)
            yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"

        if interrupts and not errored:
            async for frame in _interrupt_frames(
                ctx,
                interrupts,
                turn,
                thread_id=thread_id,
                user_id=user_id,
                user_text=user_text,
                t0=t0,
                messages=messages,
                sent_messages=sent_messages,
                observed=observed,
            ):
                yield frame
            return

        async for frame in _final_frames(
            ctx,
            turn,
            errored=errored,
            acc=acc,
            t0=t0,
            capture=capture,
            messages=messages,
            sent_messages=sent_messages,
            observed=observed,
            impl=impl,
            user_text=user_text,
            user_id=user_id,
            history_restore=history_restore,
            thread_id=thread_id,
        ):
            yield frame

    async def event_stream() -> AsyncIterator[str]:
        """턴 스트림 + **체크포인트 폐기 관문**(스펙 346).

        thread_id는 턴별 고유라 턴이 끝나면 그 체크포인트는 아무도 안 읽는다 — 여기서 지운다.
        finally라 정상 종료·에러·**클라이언트 끊김**(GeneratorExit)까지 한 지점이 덮는다.

        `paused=bool(interrupts)`가 핵심이다: 그래프가 멈춘 채면 **핀(승인 행·폼 포인터)이 아직
        안 심겼어도** 남긴다 — 핀은 interrupt 뒤에 심기므로, 그 사이 취소가 끼면 핀만 보고 판정할 때
        재개 근거를 지워버린다(codex 적대 검토 P1).
        """
        try:
            async for frame in _run_turn():
                yield frame
        finally:
            await checkpoint_retention.release_thread(thread_id, paused=bool(interrupts))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
