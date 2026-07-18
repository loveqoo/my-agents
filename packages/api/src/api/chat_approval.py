"""HIL 승인 생성·재개(스펙 041/171/188) — chat.py에서 분할(스펙 291 Phase 3b).

위험 도구 interrupt의 Approval 생성(_create_approval), admin 결재 후 그래프 재개
(resume_approval), 산출물형 ask/form 대기 포인터(_PENDING_ARTIFACT). 파사드는 chat.py(재수출 계약).
"""

import asyncio
import logging
import secrets
import time
import uuid
from typing import TYPE_CHECKING

from langgraph.types import Command
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy import update as sa_update

from agent.runtime import AgentBuildContext, AgentConfigError, CustomAgent

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.graph.state import CompiledStateGraph

from . import authz, checkpoint_retention, checkpointer, memory, observability, runtime
from .broker import BrokerContext, PolicyScopedBroker, build_providers
from .chat_context import ChatContext, _load_context
from .chat_graph_build import (
    _graph_fingerprint,
    _MemoryRecallProxy,
    _rag_tools_for,
    resolve_agent_runtime,
)
from .chat_history import _HistoryWindowProxy, _load_session_conversation, _to_base_messages
from .chat_persist import _persist, _resolve_session_for_persist
from .chat_trace import _broker_calls_trace
from .db import SessionLocal
from .models import Approval, User
from .ownership import next_owner

log = logging.getLogger("api.chat")

# 산출물형 ask/form 대기 포인터(스펙 188) — session_id → {"thread_id"}. thread_id가 턴별 고유라
# ask interrupt가 걸린 체크포인트는 이전 턴 thread에 남는다(승인은 Approval.checkpoint가 이 역할).
# 다음 사용자 입력이 오면 이 thread를 Command(resume=)로 재개한다. 프로세스 메모리(P1 경계) —
# 재시작 시 소실되면 다음 입력이 새 produce 실행으로 폴백(영속화는 후속 스펙).
# **단일 정의**(스펙 291): chat()과 재개/artifact 경로가 같은 dict 객체를 공유 — 재선언 금지.
_PENDING_ARTIFACT: dict[str, dict] = {}


async def _create_approval(
    ctx: ChatContext, thread_id: str, payload: dict, user_id: str | None
) -> str:
    """위험 도구가 그래프를 멈춘 순간 런타임 Approval(pending) 생성. checkpoint=thread_id가 재개 키.

    DB 접근은 API 계층(여기)에서만 — 도구는 순수(interrupt payload만 만든다). 이 row가
    ApprovalsView에 뜨고, resolve하면 resume_approval이 같은 thread_id로 그래프를 재개한다.

    user_id = 요청 주체(쿠키 유저 UUID str, 머신이면 None). owner self-승인(스펙 066)의 대조 기준 —
    여기서 박지 않으면 self-승인 자체가 불가능하고, NULL은 admin 전용으로 fail-closed.
    """
    apid = "apr-" + secrets.token_hex(4)
    async with SessionLocal() as db:
        # 0턴 미영속(스펙 049)이라도 *승인 게이트에 도달한 턴은 실 상호작용*이므로 여기서 세션 행을
        # 보장한다. 그래야 resume_approval의 _load_context가 같은 session_id로 세션을 찾아(새 id를
        # 안 만들고) 최종 답변을 원 세션에 영속한다(approval-resume 연속성 보존).
        sess = await _resolve_session_for_persist(db, ctx)
        if sess is not None:
            ctx.session_pk = sess.id
            ctx.session_pending = None
            # 스펙 068 D6: 승인 게이트에 도달한 턴은 실 상호작용이므로 *생성 시점*에 소유자를 박는다.
            # 이게 없으면 세션이 NULL-owned로 남아, D1(소유자 스코프 resume) 도입 후 그 턴을 시작한
            # member가 *자기 세션을* 이어가지 못한다(무회귀 깨짐). next_owner라 기존 소유자 보존·안전.
            sess.user_id = next_owner(sess.user_id, user_id)
        db.add(
            Approval(
                approval_id=apid,
                session_id=ctx.session_id,
                user_id=user_id,
                agent_pk=ctx.agent_pk,
                agent_name=ctx.agent_name,
                permission=payload.get("permission", ""),
                approver=payload.get(
                    "approver"
                ),  # 스펙 177 P2 — MCP 도구만 값 有, 그 외 None→Casbin 폴백
                action=payload.get("action", ""),
                args=payload.get("args", {}),
                summary=payload.get("summary", ""),
                checkpoint=thread_id,
                # 위상 정체 스냅샷(스펙 171) — 재개 시 impl이 바뀌었으면 stale checkpoint에
                # 다른 그래프를 resume하지 않도록 대조 기준. "" = 기본(DefaultUiAgent).
                impl=ctx.impl or "",
                status="pending",
            )
        )
        await db.commit()
    return apid


async def _build_resume_broker(
    user_id: str | None,
    capabilities: list[str] | None,
    tool_policy: dict | None = None,
    *,
    delegation_chain: tuple = (),
    delegation_budget: dict | None = None,
) -> PolicyScopedBroker:
    """재개용 스코프 브로커 — 원 요청자(user_id)의 RBAC를 재구성해 request-time 게이트를 그대로 복원.

    build_broker(principal, ...)와 **동일 술어**를 principal 객체 없이 재현한다: superuser면 우회(원
    요청과 동일 안전판), 아니면 casbin `enforce(user_id, capability:{kind}, invoke)`. user_id가 없으면
    deny(머신 발 — 이 경로는 애초에 브로커 interrupt를 못 만들므로 실질 미도달, 안전측 기본).

    로컬 위임(스펙 256) 봉합(codex 256 [P2]): 재개도 원 턴과 동일하게 (1) **원 요청자 principal 객체**를
    AgentProvider에 관통해야 하위 eval_run_agent→build_broker가 principal.id로 스코프를 재구성한다
    (없으면 크래시 → 승인된 로컬 위임이 조용히 미실행). (2) **delegation_chain**(루트 agent_id)을
    관통해야 재개 후 재위임에서도 순환·깊이 게이트가 원 턴과 동일하게 성립한다."""
    is_super = False
    requester = None  # 원 요청자 User 객체(AgentProvider가 로컬 위임 하위 실행의 RBAC 주체로 사용)
    if user_id:
        try:
            async with SessionLocal() as s:
                u = await s.get(User, uuid.UUID(user_id))
                requester = u  # 로드된 속성(id·is_superuser)은 세션 종료 후 접근 가능
                is_super = bool(u and u.is_superuser)
        except (ValueError, TypeError):
            is_super = False  # user_id가 UUID 형식이 아니면 casbin 경로로만(우회 없음)

    def rbac_allows(kind: str, name: str | None = None) -> bool:
        # per-cap 부여 지원(스펙 112) — build_broker와 **동일 술어**(`_rbac_allows`, drift 0).
        if not user_id:
            return False
        if is_super:
            return True
        from .broker import _rbac_allows

        return _rbac_allows(authz.get_enforcer(), user_id, kind, name)

    # user_id 주입(스펙 104) — MemoryProvider가 재개 경로에서도 원 요청자 스코프를 복원한다. 없으면
    # 재개 시 `memory:user`가 사라져 자기 기억 접근이 깨진다(fail-closed지만 기능 회귀, 적대 리뷰 104 P2).
    # principal(원 요청자)·delegation_chain(루트) 관통 — 로컬 위임 재개 봉합(codex 256 [P2]).
    # 스펙 294: 조립은 build_providers(BrokerContext) 단일 출처 — 브로커는 소비만.
    providers = build_providers(
        BrokerContext(
            principal=requester,
            user_id=user_id,
            delegation_chain=delegation_chain,
            delegation_budget=delegation_budget,
        )
    )
    return PolicyScopedBroker(capabilities, rbac_allows, providers, tool_policy=tool_policy)


def _impl_drifted(snap_impl: str | None, cur_impl: str | None) -> bool:
    """스펙 171 — 재개 시 impl(그래프 위상)이 생성 시점과 달라졌나. 순수 함수(단위 검증 가능).

    - snap None = 스펙 171 마이그레이션 이전에 만든 행 = 스냅샷 부재 = 대조 불가 → False(스킵, 하위호환).
    - "" = 기본(DefaultUiAgent). cur도 None/""면 기본이므로 `cur or ""`로 정규화해 대조.
    - snap이 있고 현재와 다르면 True → 재개는 미정의 동작(다른 그래프를 stale checkpoint에 resume)이라 거부.
    """
    if snap_impl is None:
        return False
    return snap_impl != (cur_impl or "")


# ---------------------------- resume_approval 단계 헬퍼 (스펙 291 분해) ----------------------------


async def _load_resume_target(
    approval: Approval,
) -> "tuple[ChatContext, CustomAgent, AsyncPostgresSaver, str] | None":
    """재개 가능성 가드 — 통과 시 (ctx, impl, ckpt, thread_id), 불가면 None(graceful 무시).

    가드: checkpoint(thread_id)·agent_pk 없으면 재개 불가. code/external 소스는 로컬 그래프가
    아니므로 애초에 approval을 만들지 않는다(여기 도달 시 graceful 무시).

    impl-drift 가드(스펙 171): approval은 생성 시점 impl의 그래프 topology로 checkpoint를 만들었다.
    그 사이 admin이 `config.impl`을 다른 impl로 바꾸면 그 checkpoint는 현 그래프와 위상이 어긋난다 —
    다른 그래프를 stale checkpoint에 resume하는 건 LangGraph 미정의 동작이라 **graceful 거부**
    (approval은 이미 결재됨·세션 무파손·approved-but-not-executed=안전방향). 다중 HIL impl 출하 중
    (DefaultUiAgent·orchestrate·orchestrate_ranked)이라 이 스왑은 실제 도달 가능(deep-reasoner 적대
    검토). 방아쇠는 admin의 impl 교체(agents:manage)에 갇혀 권한상승은 아니다. impl 스냅샷이 None인
    행(171 마이그레이션 이전)은 대조 불가라 스킵하고 supports_hil 가드로만 넘긴다(하위호환)."""

    thread_id = approval.checkpoint
    if not thread_id or not approval.agent_pk:
        log.warning("resume 건너뜀: checkpoint/agent_pk 없음 (approval %s)", approval.approval_id)
        return None
    ckpt = checkpointer.get_checkpointer()
    if ckpt is None:
        log.warning("resume 불가: 체크포인터 비활성 (approval %s)", approval.approval_id)
        return None
    # 원 턴과 동일하게 컨텍스트·도구·프롬프트를 재구성(같은 세션 id → 기존 세션 로딩, 새로 안 만듦).
    ctx = await _load_context(approval.agent_pk, approval.session_id)
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as e:
        # 선언한 구현이 미해결(스펙 089) — 재개 불가, graceful 무시(approval은 이미 결재됨, 세션 무파손).
        log.warning("resume 불가: 설정 실패 impl '%s' (approval %s)", e, approval.approval_id)
        return None
    if impl is None or ctx.model_cfg is None:
        log.warning("resume 불가: 비로컬/모델없음 소스 (approval %s)", approval.approval_id)
        return None
    if _impl_drifted(approval.impl, ctx.impl):
        log.warning(
            "resume 불가: impl drift — 생성 '%s' vs 현재 '%s' (checkpoint 위상 불일치, approval %s)",
            approval.impl or "(기본)",
            ctx.impl or "(기본)",
            approval.approval_id,
        )
        return None
    # 잔여 방어(codex F2 원본): 현 런타임이 HIL 미지원이면 애초 interrupt/checkpoint를 만들 수 없으므로
    # 재개 불가. impl-drift 가드가 impl 변경을 이미 잡으므로 대개 이 지점 도달 = impl 불변 + 원래
    # HIL 지원이나, 방어적으로 유지(예: 마이그레이션 이전 None-snap 행이 non-HIL로 바뀐 경우).
    if not impl.describe().supports_hil:
        log.warning(
            "resume 불가: 현 런타임(%s)이 HIL 미지원 — checkpoint 생성 그래프와 drift (approval %s)",
            type(impl).__name__,
            approval.approval_id,
        )
        return None
    return ctx, impl, ckpt, thread_id


def _resume_uses_memory(ctx: ChatContext, impl: CustomAgent) -> bool:
    """재개 턴 회상 게이트 — 비영속(235 대칭)·consumes 선언(233)·메모리 on·mem_cfg 존재 모두 충족."""
    consumes = impl.describe().consumes
    reads_memory = consumes is None or "memories" in consumes
    return (
        not ctx.ephemeral
        and reads_memory
        and memory.memory_enabled(ctx.memories)
        and ctx.mem_cfg is not None
    )


async def _resume_memory_inputs(
    ctx: ChatContext, impl: CustomAgent, approval: Approval
) -> "tuple[bool, list[dict], _MemoryRecallProxy | None, list[dict]]":
    """재개 경로 회상 입력 — 반환 (used_memory, mem_hits, mem_proxy, resume_recalls).

    user 축 = 원 요청자(approval.user_id — 브로커 RBAC 재확인과 동일 재료, codex 268 P2): 재개 후
    노드 회상이 원 요청자의 세션-가로지름 기억을 그대로 쓰게(원 턴과 동일 스코프). 없으면 None(머신 발).
    스펙 233 봉합(이중 배선 축 — 신규 chat과 동일 게이트를 재개 경로에도): impl이 "memories"를
    consumes로 선언할 때만 회상(폼 "무시됩니다"를 재개 경로에서도 참으로).
    재개 주체=admin이라 user/run 축 회상은 의미가 약하나, 프롬프트 톤 유지를 위해 agent 축 회상만이라도
    접목(없어도 무해). 자동 메모리 add는 user_id 부재로 생략(빚). 노드형은 선조회 생략(메인 경로 대칭,
    스펙 268 P2) — 프록시가 노드별 조회(기본 키워드=approval.summary, 원 턴과 동일 재료)."""

    recall_scope = {
        "user_id": str(approval.user_id) if approval.user_id else None,
        "run_id": ctx.session_id,
        "agent_id": ctx.ext_agent_id,
    }
    used_memory = _resume_uses_memory(ctx, impl)
    mem_hits = (
        await asyncio.to_thread(memory.search, recall_scope, approval.summary or "", ctx.mem_cfg)
        if used_memory and ctx.nodes_resolved is None
        else []
    )
    resume_recalls: list[dict] = []
    mem_proxy = (
        _MemoryRecallProxy(recall_scope, ctx.mem_cfg, approval.summary or "", resume_recalls)
        if (used_memory and ctx.nodes_resolved is not None)
        else None
    )
    return used_memory, mem_hits, mem_proxy, resume_recalls


async def _rebuild_resume_graph(
    ctx: ChatContext,
    impl: CustomAgent,
    ckpt: "AsyncPostgresSaver",
    approval: Approval,
    mem_hits: list[dict],
    mem_proxy: "_MemoryRecallProxy | None",
) -> "tuple[CompiledStateGraph, list[dict], PolicyScopedBroker, list[dict]] | None":
    """원 턴과 동일 재료로 그래프 재구성 — 반환 (graph, calls_sink, resume_broker, history_windows).
    그래프 조립 시점 설정 실패(스펙 317 — 코드 노드 impl 미등록 등)는 None(재개 불가 graceful).

    서브스텝 HIL 재개(스펙 101 §3.5): 위임 cap의 interrupt를 재개하려면 원 턴과 **동일 스코프**의
    브로커를 재주입해야 한다 — 없으면 orchestrate.delegate가 broker=None으로 위임을 통째 건너뛰어
    *승인된* cap이 영영 미실행된다(approved-but-not-executed = 거부 방향 오류). allowlist=에이전트
    config(결정적). RBAC 축은 **원 요청자**(approval.user_id)로 재확인 — 요청 시 이미 통과했고 유저
    축은 재개 사이 불변. superuser 우회도 원 요청과 동일 보존."""

    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(
        ctx.mcp_servers, calls_sink, ctx.tool_policy, ctx.tool_names
    )
    # 채팅 자가기록 도구 제거됨(스펙 051) — agent_id 메모리는 어드민 저작 전용. 회상(recall_scope)은 유지.
    # 노드형 컬렉션별 도구 포함(스펙 268 P1 — 세 입구 정합, learning 149).
    tools.extend(_rag_tools_for(ctx, calls_sink))
    # 단기 기억 창 프록시(스펙 270) — 재개는 대화를 재시드 않으므로 세션 DB서 이전 대화 재구성해 주입
    # (learning 149 미러 — 재개 후 다음 노드도 이전 대화를 봄, 무회귀). 노드형에만. 세션 없으면 빈 대화.
    resume_history_windows: list[dict] = []
    resume_hist_proxy = None
    if ctx.nodes_resolved is not None:
        resume_prior = await _load_session_conversation(approval.session_id, approval.agent_pk)
        # drop_last=False(codex 270 High): 세션 DB는 이전 대화만(현재 턴 미영속·체크포인트가 보유)이라
        # 마지막을 안 버린다 — 메인 경로처럼 버리면 직전 assistant 메시지를 잃는다.
        resume_hist_proxy = _HistoryWindowProxy(
            _to_base_messages(resume_prior),
            ctx.history_depth,
            resume_history_windows,
            drop_last=False,
        )
    prompt_prompt = ctx.prompt
    if mem_hits:
        # 브로커 memory 능력과 공유하는 포맷(스펙 104 drift 0) — 회상 텍스트 표현이 한 곳.
        recalled = memory.format_memory_hits(mem_hits)
        prompt_prompt = f"{prompt_prompt}\n\n# 관련 기억(회상됨)\n{recalled}"
    run_params = {} if ctx.temperature is None else {"temperature": ctx.temperature}
    resume_broker = await _build_resume_broker(
        approval.user_id,
        ctx.capabilities,
        ctx.tool_policy,
        # 루트 agent_id로 체인 시작(chat 신규 경로와 대칭, 스펙 256 v2) — 재개 후 재위임의 순환·깊이
        # 게이트가 원 턴과 동일하게 성립(codex 256 [P2]). 없으면 루트 재방문이 허용돼 불변식이 깨진다.
        delegation_chain=((ctx.ext_agent_id,) if ctx.ext_agent_id else ()),
        delegation_budget={"n": 0},  # 재개 턴도 자체 예산(너비 폭주 상한, codex [P2])
    )
    # 노드 에이전트-호출 도구(스펙 318) — 재개 후 다음 노드도 위임 가능(입구 정합). pipeline만.
    if ctx.impl == "pipeline":
        tools.extend(
            runtime.build_agent_tools(resume_broker, await resume_broker.agent_capabilities())
        )
    # 스펙 371 D3 정합: 원 턴이 promptless 그래프(캐시 적격)였다면 재개 그래프도 promptless로 —
    # 체크포인트 상태에 이미 선두 SystemMessage가 있어, 여기서 prompt를 구우면 system이 이중이 된다.

    _promptless = _graph_fingerprint(ctx) is not None
    build_ctx = AgentBuildContext(
        prompt="" if _promptless else prompt_prompt,
        model_cfg=ctx.model_cfg,
        tools=tools,
        checkpointer=ckpt,
        params=run_params,
        memories=mem_hits,
        overrides=ctx.overrides,
        broker=resume_broker,
        memory_recall=mem_proxy,  # 노드형 회상 프록시(스펙 268 P2) — 재개 후 다음 노드 첫 진입용
        history_window=resume_hist_proxy,  # 단기 기억 창 프록시(스펙 270) — 재개 후 다음 노드 대화 슬라이스
        # 재개도 원 턴과 동일 impl_config 재주입(노드형 노드 도구 HIL 재개·산출물형 폼 재개, 259/190).
        impl_config=(
            {"nodes": ctx.nodes_resolved} if ctx.nodes_resolved is not None else ctx.artifact_spec
        ),
    )
    try:
        graph = impl.build_graph(build_ctx)
    except AgentConfigError as e:
        # 그래프 조립 시점 설정 실패(스펙 317 — 코드 노드 impl 미등록 등). resolve 실패(위)와 동일한
        # graceful 거부 — 승인은 이미 결재됐고 세션은 무파손, 재개만 불가로 남긴다(500 누출 금지).
        log.warning(
            "resume 불가: 그래프 조립 설정 실패 '%s' (approval %s)", e, approval.approval_id
        )
        return None
    return graph, calls_sink, resume_broker, resume_history_windows


def _extract_turn_texts(result: object) -> tuple[str, str]:
    """최종 상태에서 (사용자 질문, 최종 AI 답변) 추출 — 체크포인트가 보유(Approval에 user_text 미저장)."""
    msgs = result.get("messages", []) if isinstance(result, dict) else []
    user_text = next(
        (getattr(m, "content", "") for m in msgs if getattr(m, "type", "") == "human"), ""
    )
    reply = next(
        (
            getattr(m, "content", "")
            for m in reversed(msgs)
            if getattr(m, "type", "") == "ai" and getattr(m, "content", "")
        ),
        "",
    )
    return user_text, reply


async def resume_approval(approval: Approval, decision: str) -> str | None:
    """admin 결정(approve/reject)으로 멈춘 그래프를 재개하고 최종 메시지를 원 세션에 영속.

    approvals.resolve_approval이 status 설정 후 호출(상시). 체크포인트(Postgres 공유)에서 그래프를
    재구축해 `Command(resume=...)`로 이어 달린다 — 멀티워커 안전. approve면 도구 실행 후 ReAct가
    마무리 답변을, reject면 도구 미실행으로 마무리한다. 라이브 스트리밍은 빚(§7) — 여기선
    서버사이드로 끝까지 돌려 결과만 세션에 남긴다.

    반환(스펙 388 P2, 가산): 재개 턴의 최종 답변 텍스트 — A2A 승인 브리지가 외부 호출자에게
    돌려준다. 재개 불가/실패 경로는 None(기존 graceful 유지, REST 소비자는 반환 무시).
    """
    target = await _load_resume_target(approval)
    if target is None:
        return None
    ctx, impl, ckpt, thread_id = target
    used_memory, mem_hits, mem_proxy, resume_recalls = await _resume_memory_inputs(
        ctx, impl, approval
    )
    rebuilt = await _rebuild_resume_graph(ctx, impl, ckpt, approval, mem_hits, mem_proxy)
    if rebuilt is None:
        return None  # 그래프 조립 설정 실패(스펙 317) — 재개 불가 graceful(로그는 rebuild가 남김)
    graph, calls_sink, resume_broker, resume_history_windows = rebuilt
    config = {"configurable": {"thread_id": thread_id}}
    # 관측(스펙 118→328) — 재개 경로도 OTEL이 설정됐을 때만 콜백 부착(미설정=무동작).
    # 비영속(스펙 235) 대칭 가드(codex): 정상 ephemeral은 approval을 못 만들어 미도달이나, "과거 approval +
    # 설정을 ephemeral로 변경" 엣지에서 이 경로가 호출될 수 있어 관측도 대칭으로 스킵(_persist는 이미 차단).
    if not ctx.ephemeral:
        config = observability.with_trace(config, name="chat-resume", user_id=approval.user_id)

    t0 = time.perf_counter()
    try:
        # durability="exit"(스펙 346) — 재개 경로도 그래프 종료 시점에만 체크포인트를 박는다.
        result = await graph.ainvoke(
            Command(resume={"decision": decision}), config=config, durability="exit"
        )
    except Exception as exc:
        log.error("resume 실패 (approval %s): %s", approval.approval_id, exc)
        return None

    # 체크포인트 폐기 관문(스펙 346) — 승인이 해소돼 그래프가 끝났으면 이 스레드는 죽은 것이다.
    # 재개 중 **또 멈췄으면**(두 번째 위험 도구) 그 상태가 유일한 재개 근거라 남긴다.
    if "__interrupt__" not in result:
        await checkpoint_retention.release_thread(thread_id)

    user_text, reply = _extract_turn_texts(result)
    total_ms = int((time.perf_counter() - t0) * 1000)
    tokens = runtime.estimate_tokens(len(user_text), len(reply))
    trace = runtime.assemble_trace(
        agent_id=ctx.ext_agent_id,
        memories=mem_hits,
        mcp_calls=calls_sink,
        used_memory=used_memory,
        total_ms=total_ms,
        tokens=tokens,
    )
    trace["resumedApproval"] = {"id": approval.approval_id, "decision": decision}
    if resume_broker.invocations:
        # 재개 턴의 브로커 호출도 표면화(스펙 130, codex #1).
        trace["brokerCalls"] = _broker_calls_trace(resume_broker.invocations)
    if resume_recalls:
        # 재개 후 노드 회상도 표면화(codex 268 P3 — 메인 경로 미러): 없으면 재개 답이 왜 기억을
        # 썼는지 인스펙터가 설명 못 함.
        trace["memoryRecalls"] = resume_recalls
    if resume_history_windows:
        # 재개 후 단기 기억 창도 표면화(스펙 270 — 메인 경로 미러, 재개 축 전수 재구성 규율).
        trace["historyWindows"] = resume_history_windows
    await _persist(
        ctx, user_text, reply, trace, tokens, ctx.persist_history, user_id=None, turn_id=thread_id
    )
    return reply


async def resolve_and_resume(
    approval_id: str,
    decision: str,
    *,
    principal: object,
    resolved_by: str,
    require_agent_pk: "uuid.UUID | None" = None,
    require_user_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """승인 원자 결정+재개 관문(스펙 388 P2) — A2A 브리지용. REST(approvals.resolve_approval)와
    같은 시맨틱: pending→결정 **원자 UPDATE**(WHERE status='pending' — 동시 resolve TOCTOU 차단,
    이중 실행 금지)·결정 후 resume_approval.

    반환 (status, reply, session_id): "resumed"=재개 완료(reply=최종 답변·session_id=contextId
    에코용) · "already"=이미 처리(409 의미) · "not_found"=승인 없음/스코프 불일치(**접기** —
    열거 오라클 0: 타 에이전트·타 userId의 approval_id는 부재와 동일 응답) · "forbidden"=
    결재 권한 없음(REST와 동일 — 자기 행이라 존재는 아는 상태, 403 의미).

    **결재 인가는 REST와 단일 출처**(codex 388 P2 P1 봉합): approvals._may_resolve를 공유 —
    admin/머신=전체, 비-admin은 approver="self" 스탬프 또는 casbin self_approve만. 이게 없으면
    비-admin 쿠키 유저가 A2A로 자기 승인을 스스로 approve해 위험 도구를 실행할 수 있었다.
    require_agent_pk/require_user_id: A2A 입구 스코프 — 이 에이전트의(+이 유저의) 승인만 결정 가능.
    """
    async with SessionLocal() as db:
        p = (
            await db.execute(select(Approval).where(Approval.approval_id == approval_id))
        ).scalar_one_or_none()
        if p is None:
            return "not_found", None, None
        if require_agent_pk is not None and p.agent_pk != require_agent_pk:
            return "not_found", None, None
        if require_user_id is not None and p.user_id != require_user_id:
            return "not_found", None, None
        from .approvals import (
            _may_resolve,
        )  # 지연 import(approvals→chat_approval 역방향이라 순환 회피)

        if not _may_resolve(p, principal):
            return "forbidden", None, None
        new_status = "approved" if decision == "approve" else "rejected"
        res = await db.execute(
            sa_update(Approval)
            .where(Approval.approval_id == approval_id, Approval.status == "pending")
            .values(status=new_status, resolved_at=sa_func.now(), resolved_by=resolved_by)
        )
        if res.rowcount == 0:
            return "already", None, None
        await db.commit()
        await db.refresh(p)
    reply = await resume_approval(p, decision)
    return "resumed", reply, p.session_id
