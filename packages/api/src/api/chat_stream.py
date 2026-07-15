"""스트리밍·오류 힌트·A2A 중계 — chat.py에서 분할(스펙 291 Phase 3b).

설정 오류 SSE(스펙 089), 모델 연결 힌트(스펙 058 G4), 원격 A2A 중계(_a2a_stream, 스펙 057),
로컬 에이전트 A2A 서빙(stream_local_reply, 스펙 061). 파사드는 chat.py(재수출 계약).
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from agent.runtime import AgentBuildContext, AgentConfigError

from . import a2a_client, observability, runtime
from .chat_context import _load_context
from .chat_history import _window
from .chat_persist import _mid_frame, _persist

log = logging.getLogger("api.chat")


async def _config_error_stream(impl_key: str) -> AsyncIterator[str]:
    """설정 실패(스펙 089) — 선언한 in-process 구현이 미해결. default로 만회하지 않고 SSE로 정직히
    통보한다. **클라이언트 메시지는 일반화**(impl 값 미반영) — config["impl"]은 관리자가 임의로 저장한
    값(합의 B)이라 *레지스트리 키임이 증명되지 않으며*, 채팅 클라이언트는 관리자보다 권한이 낮을 수
    있다(GET /agents의 impl은 인증 관리자 전용). 구체 키는 서버 로그에만 남겨 운영 디버깅을 보존한다
    (codex 적대 리뷰 089-F1: 미해결 impl 원문이 SSE로 새던 정보노출 봉합 — 비밀누출 0)."""
    log.warning("config_error 채팅 거부: 미해결 impl %r", impl_key)
    msg = "에이전트 설정 오류로 응답할 수 없습니다 — 관리자에게 문의하세요(런타임 구현 미해결)."
    yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


# 연결-실패로 보이는 에러의 지문(httpx/openai/asyncpg 계층 공통). model_id 불일치(404 등)나
# 인증 오류(401)는 *연결*이 아니므로 힌트를 붙이지 않는다 — 잘못된 안내가 더 혼란스럽다.
_CONN_ERR_MARKERS = (
    "connection error",
    "connection refused",
    "cannot connect",
    "all connection attempts failed",
    "connect call failed",
    "errno 61",
    "name or service not known",
    "timed out",
    "timeout",
    "apiconnectionerror",
    "connecterror",
    "max retries exceeded",
)


def _model_error_hint(exc: Exception, model_cfg: dict | None) -> str | None:
    """모델 연결 실패로 보이면 전환 힌트(없으면 None). 스펙 058 G4 — 기본 chat은 무외부 'Mock LLM'
    (스펙 059)이라 곧장 실패하지 않는다. 이 힌트는 운영자가 Provider UI로 추가한 실 모델을 기본으로
    전환했는데 그 서버가 안 떠 있을 때 첫 채팅이 연결 실패하는 경우를 위한 것이다."""
    if not model_cfg:
        return None
    blob = f"{type(exc).__name__} {exc}".lower()
    if not any(m in blob for m in _CONN_ERR_MARKERS):
        return None
    base_url = model_cfg.get("base_url", "")
    return (
        f"채팅 모델 연결 실패 (base_url={base_url}) — 모델 서버가 떠 있는지/주소가 맞는지 확인하세요. "
        "외부 모델 없이 바로 시험하려면 admin에서 기본 채팅 모델을 'Mock LLM'으로 되돌리세요"
        "(무외부 동작, 기본값)."
    )


async def _a2a_stream(ctx: dict, user_text: str, user_id: str | None) -> AsyncIterator[str]:
    """원격(A2A) 에이전트: 등록된 카드 url로 JSON-RPC message/stream 호출 → 응답을 우리 SSE로 재전송.

    code(우리가 배포한 SDK)·external(제3자) 모두 이 경로를 탄다(스펙 057: A2A 단일화). 전송은
    a2a_client 계층이 담당(JSON-RPC message/stream|send).
    """
    yield f"data: {json.dumps({'session': ctx['session_id']}, ensure_ascii=False)}\n\n"
    endpoint = ctx.get("endpoint")
    if not endpoint:
        yield f"data: {json.dumps({'error': '외부 에이전트에 A2A 엔드포인트(url)가 없습니다'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
        return

    streaming = a2a_client.card_streaming(ctx.get("card"))
    acc: list[str] = []
    errored = False
    t0 = time.perf_counter()
    # 세션 id를 A2A contextId로 — 호출당 단일 메시지지만 서버가 맥락을 잇게 한다(스펙 057, 멀티턴 보존).
    async for frame in a2a_client.a2a_stream(
        endpoint, ctx.get("token"), user_text, streaming=streaming, context_id=ctx.get("session_id")
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
        "promptRef": ctx["ext_agent_id"],
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
        turn_id = f"{ctx['ext_agent_id']}:{ctx['session_id']}:{uuid.uuid4().hex[:8]}"
        mid = await _persist(
            ctx,
            user_text,
            full,
            trace,
            tokens,
            ctx["persist_history"],
            user_id=user_id,
            turn_id=turn_id,
        )
        yield _mid_frame(mid)  # 스펙 209 P1.5 — 피드백 부착용 assistant id
    yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


async def stream_local_reply(agent_id: uuid.UUID, user_text: str) -> AsyncIterator[str]:
    """로컬(ui) 에이전트를 **A2A 서빙용**으로 실행 — 텍스트 청크만 yield(스펙 061).

    a2a_server가 노출된 로컬 에이전트의 JSON-RPC 호출을 받아 실 LangGraph 런타임을 돌릴 때 쓴다.
    기존 chat() 경로는 건드리지 않는다(핵심 채팅 무회귀) — _load_context·build_agent·astream만 재사용.
    v1 단순화(스펙 061 §6, 범위 밖): persist·HIL 승인 게이트·자동 memory-add·세션 영속 미적용
    (노출 런타임=순수 컴퓨트; 영속은 호출측 _a2a_stream이 자기 external 세션에 한다). 위험 도구는
    checkpointer=None이라 fail-closed(승인 게이트가 노출 경로엔 없음 — interrupt가 예외로 떨어짐).
    code/external 소스·모델 미해석이면 ValueError(로컬 그래프 아님 → 라우터가 4xx).
    """
    # 파사드(chat.py)가 이 모듈을 임포트하므로 역방향은 지연 import(순환 회피 — 지도 §의존 방향).
    from .chat import _rag_tools_for, resolve_agent_runtime

    ctx = await _load_context(agent_id, None)
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as e:
        # 선언한 in-process 구현 미해결(스펙 089) — 노출 서빙 거부(default 만회 없음, 라우터가 4xx).
        # 구체 impl 키는 서버 로그에만(089-F1: 임의 저장값이라 응답에 미반영 — 비밀누출 0).
        log.warning("A2A 노출 거부: 미해결 impl %r (agent %s)", str(e), agent_id)
        raise ValueError("에이전트 설정 실패: 런타임 구현 미해결(A2A 노출 불가)") from e
    if impl is None or ctx["model_cfg"] is None:
        raise ValueError("로컬(ui) 에이전트가 아니거나 채팅 모델이 없습니다(A2A 노출 불가)")
    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(
        ctx["mcp_servers"], calls_sink, ctx.get("toolPolicy"), ctx.get("tool_names")
    )
    # 노드형 컬렉션별 도구 포함(스펙 268 P1 — 세 입구 정합, learning 149). 메모리 프록시는 미주입:
    # A2A 서빙은 v1부터 메모리 자체가 범위 밖(스펙 061 — 순수 컴퓨트), 기존과 동일.
    tools.extend(_rag_tools_for(ctx, calls_sink))
    # 노드 에이전트-호출(스펙 318) — A2A 서빙은 정직한 경계(OUT): broker를 안 만든다(위임 실행 주체
    # principal 부재 — 외부 JSON-RPC 호출엔 유저 주체가 없어 하위 RBAC 스코프 불가). 노드가 agent 도구를
    # 참조하면 조용히 미바인딩되므로(스펙 265 환각 위험), 감지 시 경고로 표면화(조용한 실패 금지).
    if any(
        isinstance(t, str) and t.startswith("agent__")
        for n in (ctx.get("nodes_resolved") or [])
        if isinstance(n, dict)
        for t in (n.get("tools") or [])
    ):
        log.warning(
            "A2A 서빙 노드가 에이전트-호출 도구(agent__…)를 참조하나 서빙 경로는 위임 미지원(principal 부재) — 그 도구는 미바인딩됩니다 (agent %s)",
            agent_id,
        )
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    build_ctx = AgentBuildContext(
        prompt=ctx["prompt"],
        model_cfg=ctx["model_cfg"],
        tools=tools,
        checkpointer=None,
        params=run_params,
        overrides=ctx.get("overrides"),
        # impl_config — 노코드 impl 설정 통로(codex P2 후속: A2A 서빙이 이 세 번째 입구를 빠뜨려 노드형/
        # 산출물형 에이전트가 A2A 노출 시 기본 단일 노드로 퇴화하던 버그). 메인 채팅·승인 재개와 동일 주입.
        impl_config=(
            {"nodes": ctx["nodes_resolved"]}
            if ctx.get("nodes_resolved") is not None
            else ctx.get("artifact_spec")
        ),
        # 단기 기억 창(스펙 270): A2A 서빙은 무상태 단일 메시지(스펙 061 — 이전 대화 없음)라 history_window
        # 미주입(None). 메모리 프록시 미주입(위)과 같은 결 — 대화 축이 없으니 "재개 축 누락" 버그 아님.
    )
    try:
        graph = impl.build_graph(build_ctx)
    except AgentConfigError as e:
        # 그래프 조립 시점 설정 실패(스펙 317 — 코드 노드 impl 미등록 등). resolve 실패(위)와 동일하게
        # 구체 키는 로그만, 응답은 일반 문구(089-F1 — 임의 저장값 비반영).
        log.warning("A2A 서빙 그래프 조립 실패: %r (agent %s)", str(e), agent_id)
        raise ValueError("에이전트 설정 실패: 노드 구현 미해결(A2A 노출 불가)") from e
    # 노출 호출은 호출당 단일 메시지(맥락은 A2A contextId가 호출측 책임 — v1 서빙은 무상태).
    messages = _window([{"role": "user", "content": user_text}], ctx["history_depth"])
    # 관측(스펙 118) — checkpointer=None이라 thread_id 불요, 콜백만 병합(미설정=무동작).
    _cfg = observability.with_trace(None, name="a2a-serve-local")
    async for msg_chunk, _meta in graph.astream(
        {"messages": messages}, config=_cfg, stream_mode="messages"
    ):
        # A2A 서빙도 도구 원본 응답은 외부 소비자에게 노출 않음(스펙 092, 본문 sink와 동일 술어).
        if runtime.is_tool_message(msg_chunk):
            continue
        # content-block 리스트 → str 정규화(본문 sink와 동일, 092 codex P1).
        text = runtime._content_text(getattr(msg_chunk, "content", ""))
        if text:
            yield text
