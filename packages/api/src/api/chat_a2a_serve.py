"""로컬(ui) 에이전트 A2A 서빙 — chat_stream.py에서 분할+Command화(스펙 392 P2/P3).

스펙 061(서빙)→387(userId·기억)→388(contextId 세션·승인 브리지)의 로컬 서빙 경로.
파사드는 chat.py(재수출 계약: prepare_serve_turn·LocalServeTurn·ServeOutcome 계열).

설계(codex 자문 + Replace Function with Command):
- async generator는 값을 반환할 수 없어(PEP 525) 구현이 mutable dict `state`를 out-param으로
  넘겨 "스트림 소진 후 읽어라"를 암묵 계약으로 삼았다 — 시간 순서가 타입에 없어 취약했다.
- `LocalServeTurn`(Command)이 스트림과 최종 결과를 함께 소유한다: `prepare()`가 그래프·재료를
  조립하고, `chunks()`가 텍스트를 스트리밍하며, 소진 후 `outcome`이 ServeOutcome을 준다.
  소진 전 접근은 RuntimeError(암묵 계약의 명시화).
- 옛 `_serve_*` 헬퍼 6종이 인자로 나르던 공통 문맥(ctx·user_id·thread_id·has_ckpt…)은 전부
  인스턴스 필드로 흡수(Introduce Parameter Object — 인자 10개 → self).
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.runtime import AgentBuildContext, AgentConfigError, CustomAgent

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

from . import checkpointer, memory, observability, runtime
from .chat_context import ChatContext, _load_context
from .chat_graph_build import _rag_tools_for, resolve_agent_runtime
from .chat_history import _history_load_limit, _load_session_conversation, _window
from .chat_persist import _persist

log = logging.getLogger("api.chat")


# ── 서빙 턴 결과(스펙 392 P3 — out-param dict의 타입화) ─────────────────────────


@dataclass(frozen=True)
class ServeCompleted:
    """정상 완주 — reply는 소진된 전체 응답(영속·기억 저장 완료 후)."""

    reply: str


@dataclass(frozen=True)
class ServeApprovalRequired:
    """승인 대기 전환(스펙 388 P2) — a2a_server가 input-required Task/이벤트로 표현."""

    id: str
    action: str
    approver: str | None


@dataclass(frozen=True)
class ServeFailed:
    """실행 불가 안내(비영속 승인 불가 등) — a2a_server가 JSON-RPC error/failed로 표현."""

    message: str


ServeOutcome = ServeCompleted | ServeApprovalRequired | ServeFailed


@dataclass
class LocalServeTurn:
    """한 A2A 서빙 턴의 Command 객체 — 재료(필드)·스트림(chunks)·결과(outcome)를 함께 소유.

    사용 규약: `turn = await prepare_serve_turn(...)` → `async for text in turn.chunks()` →
    스트림 소진 후 `turn.outcome`. 소진 전 outcome 접근은 RuntimeError(구 state dict의
    "소진 후 읽기" 암묵 계약을 타입·예외로 명시화). 클라이언트 중간 이탈 시 GeneratorExit로
    영속·기억 저장이 생략될 수 있음은 종전과 동일한 정직한 경계(스펙 388)."""

    ctx: ChatContext
    graph: object  # CompiledStateGraph(런타임 타입, agent 패키지)
    messages: list[dict]
    cfg: dict
    thread_id: str
    user_id: str | None
    user_text: str
    prompt_chars: int
    has_ckpt: bool
    _outcome: ServeOutcome | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)

    @property
    def context_id(self) -> str:
        """A2A contextId = 우리 session_id(스펙 388 P1, 서버 발급·클라 에코)."""
        return self.ctx.session_id

    @property
    def outcome(self) -> ServeOutcome:
        """스트림 소진 후의 최종 결과. 소진 전 접근은 프로그래밍 오류로 즉시 죽인다(fail-loud)."""
        if self._outcome is None:
            raise RuntimeError("chunks() 소진 전 outcome 접근 — 스트림을 끝까지 소비한 뒤 읽으세요")
        return self._outcome

    async def chunks(self) -> AsyncIterator[str]:
        """서빙 턴 스트림(스펙 388) — 텍스트 청크 yield, 소진 후 outcome 확정·영속·기억 저장.

        1회용(codex 392 P2): 옛 계약은 async generator 객체라 재소진이 no-op였다 — 재호출을
        허용하면 영속·기억 저장·Approval 생성이 중복 실행되므로 명시적으로 잠근다."""
        if self._started:
            raise RuntimeError("chunks()는 1회용 스트림 — 재실행은 새 턴을 prepare하세요")
        self._started = True
        acc: list[str] = []  # 영속·자동 기억 저장용 어시스턴트 응답 누적
        interrupts: list[dict] = []
        run_kwargs: dict = {"durability": "exit"} if self.has_ckpt else {}  # 스펙 346
        try:
            async for mode, chunk in self.graph.astream(  # type: ignore[attr-defined]
                {"messages": self.messages},
                config=self.cfg,
                stream_mode=["messages", "updates"],
                **run_kwargs,
            ):
                if mode == "updates":
                    # interrupt 수집(스펙 388 P2) — 한 업데이트에 다중 interrupt 가능(메인 chat 미러).
                    if isinstance(chunk, dict) and "__interrupt__" in chunk:
                        interrupts.extend(i.value for i in chunk["__interrupt__"])
                    continue
                msg_chunk, _meta = chunk
                # A2A 서빙도 도구 원본 응답은 외부 소비자에게 노출 않음(스펙 092, 본문 sink와 동일 술어).
                if runtime.is_tool_message(msg_chunk):
                    continue
                # content-block 리스트 → str 정규화(본문 sink와 동일, 092 codex P1).
                text = runtime._content_text(getattr(msg_chunk, "content", ""))
                if text:
                    acc.append(text)
                    yield text
            if interrupts:
                # 인터럽트 턴은 영속·기억 저장 안 함(메인 chat _approval_frames 미러 — 재개가 전체 턴 영속).
                self._outcome = await self._interrupt_outcome(interrupts)
                return
            reply = "".join(acc)
            await self._persist_turn(reply)  # 영속(P1)
            await self._memory_add(reply)  # 자동 저장(스펙 387)
            self._outcome = ServeCompleted(reply)
        finally:
            # 폐기 관문(스펙 403 — codex P1②): 388 P2가 서빙에 체크포인터를 붙인 뒤에도 346 관문이
            # 없어 완료 턴의 체크포인트가 TTL까지 잔류했고, SSE abort 취소 오염 후보도 열려 있었다.
            # 메인 chat과 같은 관문·같은 취소-보호(강참조 shield) — paused=interrupt는 재개 근거 보존.
            from . import checkpoint_retention

            await checkpoint_retention.shielded_release(self.thread_id, paused=bool(interrupts))

    async def _interrupt_outcome(self, interrupts: list[dict]) -> ServeOutcome:
        """서빙 interrupt → 승인 대기 변환(스펙 388 P2).

        도구는 interrupt 이전이라 미실행(부수효과 0, 041 §3.3). 비영속은 승인 불가 안내(235)."""
        if not self.has_ckpt:
            return ServeFailed(
                "비영속(1회성) 에이전트는 승인이 필요한 도구를 사용할 수 없습니다 — "
                "승인·재개에는 기록(DB)이 필요합니다."
            )
        from .chat_approval import _create_approval

        first = interrupts[0]
        apid = await _create_approval(self.ctx, self.thread_id, first, self.user_id)
        return ServeApprovalRequired(
            id=apid, action=first.get("action", "(작업)"), approver=first.get("approver")
        )

    async def _persist_turn(self, reply: str) -> None:
        """정상 완주 턴의 영속(스펙 388 P1) — 세션·메시지 저장(0턴 lazy-create·소유자 스탬프는
        _persist가 처리). 트레이스는 최소 정직 표기(서빙은 캡처 없음)·토큰은 추정 폴백(estimated 명시)."""
        if self.ctx.ephemeral:
            return
        tokens = {**runtime.estimate_tokens(self.prompt_chars, len(reply)), "estimated": True}
        await _persist(
            self.ctx,
            self.user_text,
            reply,
            {"channel": "a2a"},
            tokens,
            store_messages=self.ctx.persist_history,
            user_id=self.user_id,
        )

    async def _memory_add(self, reply: str) -> None:
        """자동 기억 저장(스펙 387→388 P1) — 메인 chat의 _bg_memory_add와 같은 입력·스코프
        (user+run 축, agent 축 미태깅 — 스펙 029/020 누출 차단 동일).

        스트림 종료 후 인라인(마지막 청크는 이미 전달됨). 클라이언트가 중간 이탈하면 GeneratorExit로
        저장이 생략될 수 있다(정직한 경계 — 메인 경로의 detached task 보장은 후속)."""
        # 비영속(스펙 235) 전면 off — 메인 chat used_memory 게이트 미러.
        ctx = self.ctx
        if ctx.ephemeral or not (memory.memory_enabled(ctx.memories) and ctx.mem_cfg and reply):
            return
        await asyncio.to_thread(
            memory.add,
            {"user_id": self.user_id, "run_id": ctx.session_id},
            [
                {"role": "user", "content": self.user_text},
                {"role": "assistant", "content": reply},
            ],
            ctx.mem_cfg,
        )


# ── 조립(prepare) 재료 헬퍼 — 인스턴스 생성 전이라 모듈 함수 ──────────────────────


async def _recall_prompt(ctx: ChatContext, user_id: str | None, user_text: str) -> str:
    """A2A 서빙 회상(스펙 387→388 P1) — 켜져 있으면 프롬프트에 "# 관련 기억" 부착(메인 chat 미러).

    스코프 = user 축(387, userId 위임) + run 축(388 P1 — 세션이 생겨 contextId 대화 단위) +
    agent 축(스펙 029 미러). 실패는 memory.search가 흡수([] — 회상 없이 진행)."""
    # 비영속(스펙 235) 전면 off — 메인 chat used_memory 게이트 미러.
    if ctx.ephemeral or not (memory.memory_enabled(ctx.memories) and ctx.mem_cfg):
        return ctx.prompt
    recall_scope = {"user_id": user_id, "run_id": ctx.session_id, "agent_id": ctx.ext_agent_id}
    mem_hits = await asyncio.to_thread(memory.search, recall_scope, user_text, ctx.mem_cfg)
    if not mem_hits:
        return ctx.prompt
    recalled = memory.format_memory_hits(mem_hits)
    return f"{ctx.prompt}\n\n# 관련 기억(회상됨)\n{recalled}"


async def _build_serve_tools(ctx: ChatContext, agent_id: uuid.UUID) -> tuple[list, list[dict]]:
    """서빙 도구 조립(061) — MCP+노드형 RAG(스펙 268 P1, 세 입구 정합). 반환 (tools, calls_sink).

    노드 에이전트-호출(스펙 318)은 서빙 정직한 경계(OUT): broker를 안 만든다(위임 실행 주체
    principal 부재). 노드가 agent 도구를 참조하면 조용히 미바인딩되므로 감지 시 경고 표면화."""
    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(
        ctx.mcp_servers, calls_sink, ctx.tool_policy, ctx.tool_names
    )
    tools.extend(_rag_tools_for(ctx, calls_sink))
    if any(
        isinstance(t, str) and t.startswith("agent__")
        for n in (ctx.nodes_resolved or [])
        if isinstance(n, dict)
        for t in (n.get("tools") or [])
    ):
        log.warning(
            "A2A 서빙 노드가 에이전트-호출 도구(agent__…)를 참조하나 서빙 경로는 위임 미지원(principal 부재) — 그 도구는 미바인딩됩니다 (agent %s)",
            agent_id,
        )
    return tools, calls_sink


def _resolve_serve_impl(ctx: ChatContext) -> CustomAgent:
    """서빙 적격 검사(스펙 089) — impl 해석·모델 존재를 **실행 전 즉시** 판정(codex 392 P3:
    도구 빌드·기억 회상보다 먼저 — 옛 stream_local_reply의 관측 순서 보존). 실패는 ValueError
    (라우터가 4xx — 089-F1: 구체 impl 키는 서버 로그만, 응답은 일반 문구)."""
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as e:
        # 선언한 in-process 구현 미해결(스펙 089) — 노출 서빙 거부(default 만회 없음).
        log.warning("A2A 노출 거부: 미해결 impl %r (agent %s)", str(e), ctx.ext_agent_id)
        raise ValueError("에이전트 설정 실패: 런타임 구현 미해결(A2A 노출 불가)") from e
    if impl is None or ctx.model_cfg is None:
        raise ValueError("로컬(ui) 에이전트가 아니거나 채팅 모델이 없습니다(A2A 노출 불가)")
    return impl


def _build_serve_graph(
    ctx: ChatContext, impl: CustomAgent, serve_prompt: str, tools: list, ckpt: object
) -> "CompiledStateGraph":
    """서빙 그래프 조립 — AgentBuildContext 구성·build_graph. 조립 시점 설정 실패도 ValueError."""
    run_params = {} if ctx.temperature is None else {"temperature": ctx.temperature}
    build_ctx = AgentBuildContext(
        prompt=serve_prompt,
        model_cfg=ctx.model_cfg,
        tools=tools,
        checkpointer=ckpt,
        params=run_params,
        overrides=ctx.overrides,
        # impl_config — 노코드 impl 설정 통로(codex P2 후속: A2A 서빙이 이 세 번째 입구를 빠뜨려 노드형/
        # 산출물형 에이전트가 A2A 노출 시 기본 단일 노드로 퇴화하던 버그). 메인 채팅·승인 재개와 동일 주입.
        impl_config=(
            {"nodes": ctx.nodes_resolved} if ctx.nodes_resolved is not None else ctx.artifact_spec
        ),
        # 단기 기억 창(스펙 270): A2A 서빙은 세션 대화를 messages로 직접 재구성해 주입(스펙 388 P1)하므로
        # history_window 프록시 미주입(None).
    )
    try:
        return impl.build_graph(build_ctx)
    except AgentConfigError as e:
        # 그래프 조립 시점 설정 실패(스펙 317 — 코드 노드 impl 미등록 등). resolve 실패(위)와 동일하게
        # 구체 키는 로그만, 응답은 일반 문구(089-F1 — 임의 저장값 비반영).
        log.warning("A2A 서빙 그래프 조립 실패: %r (agent %s)", str(e), ctx.ext_agent_id)
        raise ValueError("에이전트 설정 실패: 노드 구현 미해결(A2A 노출 불가)") from e


async def _assemble_serve_messages(ctx: ChatContext, user_text: str) -> list[dict]:
    """멀티턴 재구성(스펙 388 P1) — 재개 세션이면 영속 대화를 창(historyDepth)으로 주입
    (메인 채팅의 서버 재구성 289 P1과 동일 부품·읽기량 상수)."""
    conversation: list[dict] = []
    if ctx.session_pk is not None and not ctx.ephemeral:
        conversation = await _load_session_conversation(
            ctx.session_id, ctx.agent_pk, limit=_history_load_limit(ctx)
        )
    return _window([*conversation, {"role": "user", "content": user_text}], ctx.history_depth)


async def prepare_serve_turn(
    agent_id: uuid.UUID,
    user_text: str,
    user_id: str | None = None,
    context_id: str | None = None,
) -> LocalServeTurn:
    """로컬(ui) 에이전트의 A2A 서빙 턴을 조립 — 반환 LocalServeTurn(Command).

    a2a_server가 노출된 로컬 에이전트의 JSON-RPC 호출을 받아 실 LangGraph 런타임을 돌릴 때 쓴다.
    기존 chat() 경로는 건드리지 않는다(핵심 채팅 무회귀) — _load_context·대화 재구성(chat_history)·
    영속(_persist)을 재사용한다.

    스펙 388 P1 — **contextId 세션 연속성**: contextId(=우리 session_id, 서버 발급·클라 에코)를
    세션으로 해석해 멀티턴을 잇는다. 소유권은 068 그대로 — own=user_id 바인딩(요청 userId가 있으면
    그 유저 소유 세션만 재개, 불일치=새 세션 발급으로 접음·오라클 0). 대화는 세션·메시지로 영속
    (channel="a2a", 관리자 세션 화면 가시 — 승인됨). 기억(387)은 user+run 축.
    스펙 388 P2 — **승인 브리지**: 체크포인터 부착(비영속 제외), interrupt를 예외로 죽이지 않고
    Approval(pending)로 변환해 outcome(ServeApprovalRequired)으로 알린다(응답 표현은 a2a_server).
    code/external 소스·모델 미해석이면 ValueError(로컬 그래프 아님 → 라우터가 4xx)."""
    ctx = await _load_context(agent_id, context_id, own=user_id)
    # 세션 출처 표기(스펙 388 P1) — lazy-create 시 channel="a2a"로(세션 화면에서 구분).
    if ctx.session_pending:
        ctx.session_pending["channel"] = "a2a"
    impl = _resolve_serve_impl(ctx)  # 적격 검사 먼저 — 도구·회상 부수효과 전에(codex 392 P3)
    tools, _calls_sink = await _build_serve_tools(
        ctx, agent_id
    )  # 싱크는 서빙 미노출(트레이스 없음)
    serve_prompt = await _recall_prompt(ctx, user_id, user_text)  # 회상(스펙 387)
    # HIL 체크포인터(스펙 388 P2, 041 미러) — 비영속은 미부착(235: 승인·재개에는 기록 필요,
    # interrupt는 발생해도 outcome=ServeFailed 안내로 접는다). thread_id는 턴별(메인 chat 규약).
    ckpt = None if ctx.ephemeral else checkpointer.get_checkpointer()
    thread_id = "a2a-" + uuid.uuid4().hex
    graph = _build_serve_graph(ctx, impl, serve_prompt, tools, ckpt)
    messages = await _assemble_serve_messages(ctx, user_text)
    # 관측(스펙 118) + 체크포인터 thread 바인딩(스펙 388 P2).
    cfg = dict(observability.with_trace(None, name="a2a-serve-local") or {})
    if ckpt is not None:
        cfg["configurable"] = {**(cfg.get("configurable") or {}), "thread_id": thread_id}
    return LocalServeTurn(
        ctx=ctx,
        graph=graph,
        messages=messages,
        cfg=cfg,
        thread_id=thread_id,
        user_id=user_id,
        user_text=user_text,
        prompt_chars=sum(len(m.get("content") or "") for m in messages),
        has_ckpt=ckpt is not None,
    )
