"""턴 런타임 준비(회상·도구·브로커·그래프 팩토리 캐시) — chat.py에서 분할(스펙 396 P4).

그래프 팩토리 캐시(스펙 371 D3, 구남님 설계)의 정의 모듈. _build_turn_runtime(구 CC 15)은
그래프 획득 3분기(_graph_for_turn — 캐시 적중/promptless 미스/비적격)를 추출해 분해했고,
반환은 dict → **ChatTurnRuntime dataclass**(스펙 396 명시 개선 — 필드 1:1, mypy 안전망).
캐시 hit 계약(스펙 371): tools는 재사용·per-turn calls_sink는 config 주입(트레이스 격리).
파사드는 chat.py(재수출 계약).
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from langgraph.types import Command

from agent.runtime import AgentBuildContext, CustomAgent

from . import checkpointer, memory, observability, runtime, trace_capture
from .broker import PolicyScopedBroker, build_broker
from .chat_approval import _PENDING_ARTIFACT
from .chat_context import ChatContext
from .chat_graph_build import _graph_fingerprint, _MemoryRecallProxy, _rag_tools_for
from .chat_history import (
    _build_sent_messages,
    _HistoryWindowProxy,
    _to_base_messages,
    _window,
)
from .models import User
from .schemas import ChatRequest

# ── 그래프 팩토리 캐시(스펙 371 D3, 구남님 설계) ────────────────────────────────
# 그래프는 원래 무상태(랭그래프 동시성 안전) — 요청별 상태를 호출 인자로 옮긴 뒤(promptless 빌드 +
# config sink) 빌드 결정 요소의 지문으로 캐시한다. 호출부는 신규/캐시본 구분을 모른다(팩토리가 은닉).
# 오버라이드는 우회가 아니라 지문에 흡수: 모델/도구가 다르면 다른 지문=다른 엔트리.
_GRAPH_CACHE: dict[str, dict] = {}  # fp → {"graph", "tools", "hint"}
_GRAPH_CACHE_MAX = 128
graph_cache_stats = {"hits": 0, "misses": 0}


@dataclass
class ChatTurnRuntime:
    """턴 실행 재료(스펙 396 — 구 turn dict의 타입화, 필드 1:1). _build_turn_runtime이 생성."""

    graph: Any  # CompiledStateGraph(런타임 타입)
    broker: PolicyScopedBroker
    tools: list
    calls_sink: list[dict]
    pipeline: bool
    prompt_prompt: str
    add_scope: dict
    recall_scope: dict
    used_memory: bool
    mem_hits: list[dict]
    memory_recalls: list[dict]
    history_windows: list[dict]
    prompt_in_messages: bool  # 스펙 371 D3 — promptless 그래프면 시스템 프롬프트를 seed 선두로
    seed_system: str
    build_ms: dict = field(default_factory=dict)


async def _memory_inputs(
    ctx: ChatContext, impl: CustomAgent, user_id: str | None, user_text: str
) -> tuple[dict, dict, bool, list[dict], _MemoryRecallProxy | None, list[dict]]:
    """회상 입력 준비 — 반환 (add_scope, recall_scope, used_memory, mem_hits, mem_proxy, memory_recalls).

    메모리 스코프(다층 — 스펙 020/029). 회상(search)과 자동 쓰기(add)는 **축이 다르다**:
    - recall_scope: user_id(세션 가로지름)+run_id(세션 단기)+agent_id(에이전트 전용 — 스펙 029).
      search는 축별로 따로 검색해 합집합 병합(mem0 필터는 AND이므로 — memory.py 참고).
    - add_scope: user_id+run_id만. **agent_id는 자동 add에 절대 태깅하지 않는다** — 유저 턴
      자동추출이 agent_id로 새면 user A의 사적 사실이 다른 유저에게 회상된다(스펙 020 누출 차단).
      agent_id 쓰기는 **관리자 저작(agents.py CRUD)으로만** — 채팅 자가기록은 제거됨(스펙 051).

    스펙 233 발견 봉합: 회상은 impl 실행 전 플랫폼 선처리라 impl의 consumes를 무시했다 — 편집 폼은
    "이 실행 방식은 기억을 무시합니다"라 경고하는데(스펙 206) 런타임은 회상해 **거짓 표시**였다.
    사용자 결정(타입별 게이트): impl이 "memories" 표면을 consumes로 선언했을 때만 회상·자동기록.
    consumes=None(미선언)은 게이트 안 함(스펙 206 "폼 전부 노출" 계약과 정합 — 무회귀).
    노드형(스펙 268 P2): 선(先)조회 대신 **캐싱 회상 프록시**를 주입 — 노드가 각자 조회하고 같은
    키워드는 캐시로 수렴(비용 1회). 선조회를 함께 돌리면 이중 검색이라 노드형은 mem_hits=[]."""
    add_scope = {"user_id": user_id, "run_id": ctx.session_id}
    recall_scope = {**add_scope, "agent_id": ctx.ext_agent_id}
    consumes = impl.describe().consumes
    reads_memory = consumes is None or "memories" in consumes
    used_memory = (
        not ctx.ephemeral  # 비영속(스펙 235): 회상·자동기록 전면 off(stateless)
        and reads_memory
        and memory.memory_enabled(ctx.memories)
        and ctx.mem_cfg is not None
    )
    pipeline = ctx.nodes_resolved is not None
    mem_hits = (
        await asyncio.to_thread(
            memory.search,
            recall_scope,
            user_text if ctx.memory_user_text is None else ctx.memory_user_text,
            ctx.mem_cfg,
        )
        if used_memory and not pipeline
        else []
    )
    memory_recalls: list[dict] = []
    mem_proxy = (
        _MemoryRecallProxy(
            recall_scope,
            ctx.mem_cfg,
            user_text if ctx.memory_user_text is None else ctx.memory_user_text,
            memory_recalls,
        )
        if (used_memory and pipeline)
        else None
    )
    return add_scope, recall_scope, used_memory, mem_hits, mem_proxy, memory_recalls


async def _turn_tools(
    ctx: ChatContext, cached: dict | None, calls_sink: list[dict]
) -> tuple[list, float, float]:
    """턴 도구 확보(스펙 396 분해) — 캐시 적중=tools 재사용(빌드 생략), 미스=MCP+RAG 빌드.
    반환 (tools, t_mcp, t_rag) — buildMs 계측 시각 포함(적중 시 두 시각 동일=0ms)."""
    if cached is not None:
        graph_cache_stats["hits"] += 1
        now = time.perf_counter()
        return cached["tools"], now, now
    tools = await runtime.build_mcp_tools(
        ctx.mcp_servers,
        calls_sink,
        ctx.tool_policy,
        ctx.tool_names,
        # 첨부 유래 턴(스펙 415 P4) — 정책 없는 도구도 승인 강제. 캐시 적중 경로는 지문에
        # attachment_context가 포함돼(chat_graph_build) 강제/비강제 그래프가 분리 캐시된다.
        force_approval=ctx.attachment_context,
    )
    t_mcp = time.perf_counter()
    # 채팅 자가기록 도구는 제거됨(스펙 051) — agent_id 메모리는 어드민 저작 전용. 회상은 유지.
    # RAG 검색 도구 — vectorTables가 실 컬렉션으로 해석됐을 때만(스펙 037). 노드형은 컬렉션별 도구
    # 추가(스펙 268 P1 — _rag_tools_for).
    tools.extend(_rag_tools_for(ctx, calls_sink))
    return tools, t_mcp, time.perf_counter()


def _graph_for_turn(
    fp: str | None, cached: dict | None, impl: CustomAgent, build_ctx: AgentBuildContext
) -> tuple[Any, str]:
    """그래프 획득 3분기(스펙 396 분해) — 반환 (graph, seed_hint).

    ① 캐시 적중: 그대로 재사용. ② 지문 적격 미스: promptless 빌드(스펙 371 D3 — 시스템 프롬프트는
    seed 선두 SystemMessage로, 스파이크 실증) 후 캐시 저장(+최고령 축출). discovery 힌트는 도구
    집합의 함수라 캐시 엔트리에 동봉. ③ 비적격(fp=None): 종전 그대로 직접 빌드."""
    if cached is not None:
        return cached["graph"], cached["hint"]
    if fp is not None:
        from agent.toolbox import DISCOVERY_HINT, effective_tools

        _, _discovery = effective_tools(build_ctx.tools)
        seed_hint = f"\n\n# 도구 안내\n{DISCOVERY_HINT}" if _discovery else ""
        graph = impl.build_graph(
            AgentBuildContext(
                prompt="",
                model_cfg=build_ctx.model_cfg,
                tools=build_ctx.tools,
                checkpointer=build_ctx.checkpointer,
                params=build_ctx.params,
                memories=build_ctx.memories,
                overrides=build_ctx.overrides,
                broker=build_ctx.broker,
                memory_recall=build_ctx.memory_recall,
                history_window=build_ctx.history_window,
                impl_config=build_ctx.impl_config,
            )
        )
        graph_cache_stats["misses"] += 1
        if len(_GRAPH_CACHE) >= _GRAPH_CACHE_MAX:
            _GRAPH_CACHE.pop(next(iter(_GRAPH_CACHE)))  # 최고령 축출(삽입순)
        _GRAPH_CACHE[fp] = {"graph": graph, "tools": build_ctx.tools, "hint": seed_hint}
        return graph, seed_hint
    return impl.build_graph(build_ctx), ""


async def _build_turn_runtime(
    ctx: ChatContext,
    impl: CustomAgent,
    principal: User | str,
    user_id: str | None,
    user_text: str,
    conversation: list[dict],
) -> ChatTurnRuntime:
    """그래프 빌드 재료(회상·창 프록시·도구·브로커·프롬프트) 준비 — ChatTurnRuntime 반환."""
    # 빌드 단계별 계측(스펙 368) — 매턴 재구성 비용을 분해해 trace.buildMs로 노출(캐시 367-D의 잣대).
    # 단계 사이 소량 글루(프록시 생성·프롬프트 결합)는 인접 단계에 귀속(오차 서브 ms).
    _t0 = time.perf_counter()
    (
        add_scope,
        recall_scope,
        used_memory,
        mem_hits,
        mem_proxy,
        memory_recalls,
    ) = await _memory_inputs(ctx, impl, user_id, user_text)
    _t_mem = time.perf_counter()
    pipeline = ctx.nodes_resolved is not None
    # 단기 기억 창 프록시(스펙 270) — 노드형에만 주입. 전체 대화를 쥐고 노드별 depth로 슬라이스(현재 턴은
    # 그래프가 별도 시드하므로 프록시는 [:-1]로 분리). 기본 depth=에이전트 historyDepth(노드 미지정 시 상속).
    # 스펙 289 P1: 서버 재구성분 포함 conversation — 노드형도 첫 노드부터 이어진 대화 승계.
    history_windows: list[dict] = []
    hist_proxy = (
        _HistoryWindowProxy(_to_base_messages(conversation), ctx.history_depth, history_windows)
        if pipeline
        else None
    )
    calls_sink: list[dict] = []
    # 그래프 팩토리(스펙 371 D3) — 지문 적격이면 캐시 조회. 적중 시 도구 빌드·컴파일 전부 생략
    # (도구는 config sink라 공유 안전 — 트레이스는 per-turn calls_sink로 분리).
    fp = _graph_fingerprint(ctx, impl)
    cached = _GRAPH_CACHE.get(fp) if fp else None
    tools, _t_mcp, _t_rag = await _turn_tools(ctx, cached, calls_sink)
    # 회상된 기억은 prompt(시스템 프롬프트)에 합친다. 별도 system 메시지로 주입하면
    # create_agent의 system_prompt와 충돌해 모델 채팅 템플릿이 거부한다
    # ("System message must be at the beginning"). 단일 system 프롬프트 유지.
    prompt_prompt = ctx.prompt
    if mem_hits:
        # 브로커 memory 능력과 공유하는 포맷(스펙 104 drift 0) — 회상 텍스트 표현이 한 곳.
        recalled = memory.format_memory_hits(mem_hits)
        prompt_prompt = f"{prompt_prompt}\n\n# 관련 기억(회상됨)\n{recalled}"
    run_params = {} if ctx.temperature is None else {"temperature": ctx.temperature}
    # HIL 체크포인터(스펙 041). 있으면 위험 도구가 interrupt로 일시정지·재개될 수 있다. 없으면
    # 기존 무상태 동작(무회귀) — 단 위험 도구가 호출되면 interrupt가 예외로 새 fail-closed(미실행).
    # 비영속(스펙 235): 체크포인터 미부착 → 그래프 무상태 실행. **정정(스펙 237 실측)**: 체크포인터가
    # 없어도 interrupt 자체는 발생한다 — 승인 경로의 DB 쓰기는 _approval_frames의 ephemeral 게이트가
    # 막는다(여기만으론 불충분).
    ckpt = None if ctx.ephemeral else checkpointer.get_checkpointer()
    # 능력 브로커(스펙 100) — 정책(에이전트 allowlist ∩ 유저 RBAC)으로 **미리 스코프**해 주입.
    # 로컬(ui) 실행 경로에만 준다: 원격 통째 프록시(_a2a_stream)는 broker 미주입(bypass 보존).
    # broker를 쓰는 flow(예: orchestrate)만 소비하고, 안 쓰면 무해(deny-by-default).
    # 스펙 256 v2: 루트 실행도 자기 id로 체인 시작 — 하위 어디서도 루트 재호출(순환) 불가.
    broker = build_broker(
        principal,
        ctx.capabilities,
        ctx.tool_policy,
        ctx.rag_min_scores,
        delegation_chain=((ctx.ext_agent_id,) if ctx.ext_agent_id else ()),
        delegation_budget={"n": 0},
        force_approval=ctx.attachment_context,  # 스펙 415 P4 — 첨부 유래 턴 부수효과 cap 승인 강제
    )
    # 노드 에이전트-호출 도구(스펙 318) — 노드형 노드가 `agent__{id}`로 다른 에이전트에 위임. broker
    # 경유라 재귀 가드·HIL·격리 승계(runtime.build_agent_tools). pipeline만(비노드형은 broker.discover
    # 경로라 도구 풀에 얹지 않는다 — 행위 보존). 후보=broker가 이미 스코프(권한 상승 0).
    if ctx.impl == "pipeline":
        tools.extend(runtime.build_agent_tools(broker, await broker.agent_capabilities()))
    _t_broker = time.perf_counter()
    build_ctx = AgentBuildContext(
        prompt=prompt_prompt,
        model_cfg=ctx.model_cfg,
        tools=tools,
        checkpointer=ckpt,
        params=run_params,
        memories=mem_hits,
        overrides=ctx.overrides,
        broker=broker,
        memory_recall=mem_proxy,  # 노드별 캐싱 회상 프록시(스펙 268 P2) — 비노드형은 None(무회귀)
        history_window=hist_proxy,  # 단기 기억 창 프록시(스펙 270) — 비노드형은 None(에이전트 _window 경로 유지)
        # impl_config — 노코드 impl용 설정 통로. 노드형(259)=해석된 노드, 산출물형(190)=필드 명세.
        # 에이전트당 impl 하나라 상호배타(둘 중 해당하는 것만 실림, 그 외 impl은 무시).
        impl_config=(
            {"nodes": ctx.nodes_resolved} if ctx.nodes_resolved is not None else ctx.artifact_spec
        ),
    )
    graph, seed_hint = _graph_for_turn(fp, cached, impl, build_ctx)
    _t_graph = time.perf_counter()
    _ms = lambda a, b: round((b - a) * 1000, 1)  # noqa: E731
    return ChatTurnRuntime(
        graph=graph,
        broker=broker,
        tools=tools,
        calls_sink=calls_sink,
        pipeline=pipeline,
        prompt_prompt=prompt_prompt,
        add_scope=add_scope,
        recall_scope=recall_scope,
        used_memory=used_memory,
        mem_hits=mem_hits,
        memory_recalls=memory_recalls,
        history_windows=history_windows,
        # 스펙 371 D3 — promptless 그래프면 시스템 프롬프트(+discovery 힌트)를 seed 선두 메시지로.
        prompt_in_messages=fp is not None,
        seed_system=(prompt_prompt + seed_hint) if fp is not None else prompt_prompt,
        build_ms={
            "memory": _ms(_t0, _t_mem),
            "mcp": _ms(_t_mem, _t_mcp),
            "rag": _ms(_t_mcp, _t_rag),
            "broker": _ms(_t_rag, _t_broker),
            "graph": _ms(_t_broker, _t_graph),
            "total": _ms(_t0, _t_graph),
        },
    )


def _resolve_graph_entry(
    ctx: ChatContext, body: ChatRequest, user_text: str
) -> tuple[str, Command | None, dict | None]:
    """산출물 pending 재개/새 thread 결정(스펙 188) — 반환 (thread_id, graph_input, pending_artifact).
    graph_input=None이면 새 실행(호출측이 {"messages": seed}로 채움).

    thread_id는 **턴별 고유**(세션-안정 아님): 세션-안정으로 두고 매 턴 전체 히스토리를 넘기면
    체크포인트의 add_messages 리듀서가 메시지를 중복 누적한다(무상태 윈도잉과 충돌). 턴마다 새
    thread를 만들어 그 턴의 일시정지/재개에만 쓰고, Approval.checkpoint에 박아 재개 키로 삼는다.
    산출물형 ask/form 대기(스펙 188)면 **그 thread를 이어** Command(resume=union 봉투)로 재개한다
    (새 실행 금지 — produce의 기록된 답 리플레이가 그 체크포인트에 있다). pop = 재개 시도는 1회.
    이중 입력 일급: 폼 대기 중이라도 텍스트가 오면 {"type":"text"}로 재개(병합은 뼈대 ctx.form 소유)."""
    pending_artifact = _PENDING_ARTIFACT.pop(ctx.session_id, None)
    if body.form is not None and (
        pending_artifact is None or body.form.formId != pending_artifact.get("form_id")
    ):
        # 폼 제출인데 대응 pending이 없거나 formId 불일치(스테일/위조/재시작 소실) — 조용히 텍스트로
        # 오인하지 않고 명시적으로 거절(fail-closed). pending은 원복(유효한 폼이 남아 있으면 재사용).
        if pending_artifact is not None:
            _PENDING_ARTIFACT[ctx.session_id] = pending_artifact
        raise HTTPException(
            status_code=409, detail="폼이 만료되었거나 일치하지 않습니다 — 다시 시도해 주세요."
        )
    if pending_artifact:
        thread_id = pending_artifact["thread_id"]
        if body.form is not None and pending_artifact.get("kind") == "form":
            # 서버측 1차 검증(값∈후보·알려진 key만) — 뼈대 ctx.form이 같은 함수로 재검증(이중 게이트).
            from agent.flows.artifact import validate_form_values

            vals = validate_form_values(pending_artifact.get("fields") or [], body.form.values)
            graph_input = Command(resume={"type": "form", "values": vals})
        else:
            graph_input = Command(resume={"type": "text", "message": user_text})
    else:
        thread_id = f"{ctx.ext_agent_id}:{ctx.session_id}:{secrets.token_hex(4)}"
        graph_input = None
    return thread_id, graph_input, pending_artifact


def _turn_config(
    ctx: ChatContext,
    thread_id: str,
    user_id: str | None,
    capture: trace_capture.TraceCaptureHandler,
    calls_sink: list[dict] | None = None,
) -> dict:
    """LangGraph 실행 config — 관측 콜백(스펙 118)·실측 캡처(스펙 205)·per-turn 트레이스 sink(스펙 371).

    mcp_calls_sink: 캐시된 그래프의 도구(_wrap_mcp_tool·build_rag_tool)가 호출 시점에 읽는 이 턴의
    기록 리스트 — 그래프를 턴끼리 공유해도 트레이스가 안 섞인다(구성→호출 인자 이동)."""
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if calls_sink is not None:
        config["configurable"]["mcp_calls_sink"] = calls_sink
    # 관측(스펙 118→328) — OTEL이 설정됐을 때만 콜백 부착(미설정=무동작). 핵심 채팅 경로 무영향.
    # 비영속(스펙 235): 외부 관측 기록도 스킵(고트래픽·기록 무의미 계약 — 앱 DB 밖이라도 적재 안 함).
    if not ctx.ephemeral:
        config = observability.with_trace(
            config,
            name=f"chat:{ctx.ext_agent_id}",
            session_id=ctx.session_id,
            user_id=user_id,
        )
    # 실측 캡처(스펙 205) — 모델 호출 메시지·usage. OTEL 콜백과 병행(둘 다 callbacks 리스트).
    config["callbacks"] = [*list(config.get("callbacks") or []), capture]
    return config


def _seed_and_sent(
    conversation: list[dict],
    ctx: ChatContext,
    pipeline: bool,
    prompt_prompt: str,
    system_in_seed: bool = False,
) -> tuple[list[dict], list[dict], list[dict]]:
    """윈도 절단·전송 전문·그래프 시드 — 반환 (messages, sent_messages, seed_messages).

    실행 컨텍스트를 historyDepth로 절단(최근 N개만 모델에 전달). 스펙 289 P1: 원천=conversation
    (서버 모드면 DB 재구성분 포함) — 절단 규칙은 동일. 전송 프롬프트 전문(스펙 131)은 실제 그래프
    입력을 캡·마스킹해 캡처. 노드형(스펙 270): 대화를 히스토리 프록시가 노드별 depth로 슬라이스하므로
    그래프엔 **현재 턴만** 시드(이전 대화는 프록시가 각 노드에 주입). 비노드형은 윈도된 전체를 그대로
    시드(무회귀). sent_messages는 에이전트-레벨 뷰로 유지(상속 노드=동일 집합, 커스텀 depth는 node
    timeline 192·historyWindows로 관측)."""
    messages = _window(conversation, ctx.history_depth)
    sent_messages = _build_sent_messages(prompt_prompt, messages)
    seed_messages = messages[-1:] if (pipeline and messages) else messages
    if system_in_seed and prompt_prompt:
        # promptless 그래프(스펙 371 D3) — 시스템 프롬프트를 그래프 입력 선두로(스파이크 실증:
        # system_prompt=None + 단일 선두 system = 기존과 동일 동작, 상태에 1개만).
        seed_messages = [{"role": "system", "content": prompt_prompt}, *seed_messages]
    return messages, sent_messages, seed_messages
