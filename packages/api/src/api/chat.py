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
    _stream_reasoning,
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
    # 파일첨부 주입(스펙 404) — user_text 확정 **전**에 마지막 user 메시지를 재작성해야
    # user_text·conversation·영속·히스토리 재구성이 전부 같은(주입된) 본문을 본다.
    # 단, 메모리 축(회상·자동 저장)은 **주입 전 원발화**만 봐야 한다(스펙 407) — 캡처해 ctx로.
    ctx.memory_user_text = body.messages[-1].content if body.messages else ""
    # 현재 턴 유저 입력 상한(스펙 415 P2, 승인값 5만자) — 스키마 15만자는 클라 관리 모드의 주입
    # 영속본 echo를 수용하는 구조 캡이고, **새로 치는 입력**의 가시 한계는 여기서 강제한다.
    # codex 415 P2: **마지막 user 메시지**로 검사한다(끝에 assistant를 붙여 마지막 위치 검사를
    # 우회하던 구멍). 펜스 마커를 담은 메시지는 주입 echo(재생)라 면제(스키마 15만자가 관할).
    _last_user = next(
        (m.content for m in reversed(body.messages) if m.role == "user"), None
    )
    if _last_user is not None and "⟦첨부 " not in _last_user and len(_last_user) > 50_000:
        raise HTTPException(
            status_code=422, detail="메시지가 너무 깁니다 — 한 번에 5만자까지 보낼 수 있습니다."
        )
    if body.attachments:
        if _is_remote(ctx.source):
            raise HTTPException(
                status_code=422,
                detail="파일첨부는 로컬 에이전트에서만 지원합니다(원격 A2A는 카드 계약 밖).",
            )
        from .chat_attachments import apply_attachments

        ctx.attachments_trace = apply_attachments(body)
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
    # 첨부 유래 컨텍스트 판정(스펙 415 P4) — 이번 턴 첨부 **또는** 대화에 첨부 펜스 존재(주입본이
    # 영속돼 히스토리로 재생되므로 "이번 턴만" 보면 다음 턴부터 강제가 풀리는 재생 구멍). 판정은
    # conversation(서버 재구성 포함) 확정 직후 한 번 — 그래프 빌드·브로커가 이 플래그를 소비한다.
    ctx.attachment_context = bool(body.attachments) or any(
        "⟦첨부 " in (m.get("content") or "") for m in conversation
    )
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
                    # 사고 과정(스펙 410) — 본문과 분리된 side channel. acc(영속·메모리)엔 안 넣고
                    # 별도 프레임으로만(축 분리). 사고 없는 응답이면 빈 문자열이라 프레임 없음.
                    # 노드 태그(스펙 413) — 노드형은 노드마다 사고가 나므로 어느 노드인지 실어(langgraph_node)
                    # FE가 노드별 ThoughtChain으로 가른다. 직접형은 단일 노드라 태그가 하나(단일 Think 유지).
                    reasoning = _stream_reasoning(msg_chunk)
                    if reasoning:
                        _node = _meta.get("langgraph_node") if isinstance(_meta, dict) else None
                        _frame = {"reasoning": reasoning, "node": _node} if _node else {"reasoning": reasoning}
                        yield f"data: {json.dumps(_frame, ensure_ascii=False)}\n\n"
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
            # 취소-보호(스펙 403): 클라이언트 이탈이 이 finally 도중까지 취소하면 release가
            # 반쯤 돈 채 끊겨 체크포인터 커넥션이 오염된다("another command in progress" —
            # 402 실측, 후속 요청 비결정 500의 한 축). 관문 헬퍼가 강참조+shield로 완주 보장
            # (codex 403 P1 반영) — 정상 종료 경로 시맨틱(346 폐기 관문)은 동일.
            await checkpoint_retention.shielded_release(thread_id, paused=bool(interrupts))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
