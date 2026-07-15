"""등록된 에이전트와의 대화 (SSE 스트리밍).

prompt + (선택)mem0 장기 메모리 + (선택)MCP 합성 툴을 LangGraph로 합성해 실행하고,
세션/메시지/트레이스를 영속화한다. 트레이스는 Playground 인스펙터가 소비.

지배 스펙: docs/spec/007-real-agent-service.md (Phase 2)

스펙 291(Phase 3b): 관심사별 형제 모듈(chat_context/history/persist/trace/stream/approval)로
분할 — 이 모듈은 **파사드**로 전 심볼을 재수출한다. 외부의 `from api.chat import X` /
`from api import chat` 접근은 전부 무변경(재배선 없는 분할 계약).
"""

import asyncio
import json
import logging
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

# ── 파사드 재수출(스펙 291) — 분할 전 chat.py의 공개 표면 전량 보존(외부 import 무변경) ──
from langchain_core.messages import (  # noqa: F401
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.types import Command
from sqlalchemy import select  # noqa: F401
from sqlalchemy.exc import IntegrityError  # noqa: F401
from sqlalchemy.orm import selectinload  # noqa: F401

from agent.runtime import (
    AgentBuildContext,
    AgentConfigError,
    CustomAgent,
    DefaultUiAgent,
    get_agent_impl,
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
from .auth import current_principal
from .broker import PolicyScopedBroker, build_broker  # noqa: F401
from .chat_approval import (  # noqa: F401
    _PENDING_ARTIFACT,
    _build_resume_broker,
    _create_approval,
    _impl_drifted,
    resume_approval,
)
from .chat_context import (  # noqa: F401
    _NODE_OVERRIDE_FIELDS,
    _is_remote,
    _load_context,
    _merge_node_overrides,
    _resolve_node_models,
    derive_pipeline_pool,
    resolve_agent_mem_cfg,
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
from .chat_stream import (  # noqa: F401
    _CONN_ERR_MARKERS,
    _a2a_stream,
    _config_error_stream,
    _model_error_hint,
    stream_local_reply,
)
from .chat_trace import _OVERRIDE_TRACE_KEYS, _broker_calls_trace, _overrides_trace  # noqa: F401
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


def resolve_agent_runtime(ctx: dict) -> CustomAgent | None:
    """이 에이전트의 **in-process 런타임 구현**을 해석한다(스펙 085 + 089 폴백 교정).

    - 원격(code/external) → None: 인터페이스 미대상 → 호출측이 `_a2a_stream` fallback(지금처럼).
    - 로컬(ui) + impl 미선언 → `DefaultUiAgent`(레퍼런스 적합, 정상 default).
    - 로컬(ui) + impl 적중(적합) → 그 커스텀 에이전트.
    - 로컬(ui) + impl 선언했으나 미해결(미등록/부적합) → **`AgentConfigError` raise**(스펙 089 교정3):
      `DefaultUiAgent`로 *만회·폴백하지 않는다* — 등록/설정 실수를 default가 가리지 않게 서빙을
      거부한다. 호출측이 잡아 정직히 통보.

    `impl`은 레지스트리의 *키*일 뿐 코드가 아니다 — eval/import 경로 없음(스펙 085 §보안경계)."""
    if _is_remote(ctx["source"]):
        return None
    impl_key = ctx.get("impl")
    if not impl_key:
        return DefaultUiAgent()
    inst = get_agent_impl(impl_key)
    if inst is None:
        raise AgentConfigError(impl_key)
    return inst


def _rag_tools_for(ctx: dict, calls_sink: list[dict]) -> list:
    """RAG 검색 도구 목록. 기본=전체 컬렉션 단일 도구(search_documents, 무회귀). 노드형(스펙 268 P1)은
    **컬렉션별 도구**(`search_documents__<컬렉션>`, _safe_name — 265 이름 체계)를 추가로 빌드해 노드가
    컬렉션을 골라 참조한다("검색 노드는 A만, 검증 노드는 B만"). 참조 안 된 도구는 노드 필터에서 그냥
    안 쓰임(무해). 구저장 민이름(search_documents)은 전체-컬렉션 도구로 계속 해석."""
    tools: list = []
    if not ctx.get("rag_collections"):
        return tools
    ms = ctx.get("rag_min_scores")
    tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink, ms))
    if ctx.get("nodes_resolved") is not None:
        for col in ctx["rag_collections"]:
            tools.append(
                runtime.build_rag_tool(
                    [col],
                    calls_sink,
                    ms,
                    name=runtime._safe_name("search_documents", col["name"]),
                )
            )
    return tools


class _MemoryRecallProxy:
    """노드별 회상 프록시(스펙 268 P2, 사용자 설계) — 노드형 노드가 **각자** 회상을 조회하고, 여기서
    **키워드로 캐싱**한다(같은 키워드=캐시 반환 → 비용 자연 수렴 1회, 다른 키워드=개별 조회). 이로써
    "1회 조회→노드 매핑"과 "노드별 키워드 조회"가 한 메커니즘으로 통일된다.

    - 수명 = **한 턴**(요청) — 턴을 넘겨 캐시하면 새 기억이 안 보이므로 금지.
    - 스코프는 플랫폼이 생성 시 **고정**(RBAC — 노드가 남의 기억을 못 봄, 브로커 주입 선례).
    - 조회마다 (node, query, hits, cached)를 기록(스펙 082 — 조회 행위 계측) → trace["memoryRecalls"].
    - 반환은 **포맷된 텍스트**(format_memory_hits) — 엔진(agent 패키지)이 api 모듈에 비의존."""

    def __init__(
        self, scope: dict, mem_cfg: dict | None, default_query: str, records: list[dict]
    ) -> None:
        self._scope = dict(scope)
        self._cfg = mem_cfg
        self._default = default_query or ""
        self._cache: dict[str, tuple[str, list[dict]]] = {}  # query → (포맷 텍스트, 회상 히트)
        self.records = records

    async def __call__(self, query: str | None = None, node: str = "") -> str:
        q = (query if isinstance(query, str) and query.strip() else self._default).strip()[:300]
        if not q:
            return ""
        cached = q in self._cache
        if not cached:
            hits = await asyncio.to_thread(memory.search, self._scope, q, self._cfg)
            self._cache[q] = (memory.format_memory_hits(hits) if hits else "", hits)
        text, hits = self._cache[q]
        # 기록 쿼리는 비밀 마스킹(codex 268 P3 — 타 트레이스 표면과 정합): input 모드 키워드는 앞 노드
        # 출력이라 비밀이 섞일 수 있음(_sanitize가 sk-… 등 마스킹, 캡 120).
        self.records.append(
            {
                "node": node,
                "query": memory._sanitize(q, cap=120),
                "hits": len(hits),
                "cached": cached,
                # 회상 내용(스펙 359) — 표준 retrieve_memory 경로(t.memories)와 같은
                # {text, score, scope} 리스트로 실어 인스펙터가 MemoryRow로 렌더한다. 내용 마스킹은
                # 표준 경로와 파리티(자기 스코프 저장 기억, 이미 무마스킹 노출 — 새 노출 아님).
                "memories": hits,
            }
        )
        return text


# ---------------------------- chat() 단계 헬퍼 (스펙 291 분해) ----------------------------


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


async def _prepare_conversation(ctx: dict, body: ChatRequest) -> tuple[list[dict], dict | None]:
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
    if (
        ctx.get("session_pk") is not None
        and len(body.messages) == 1
        and body.messages[0].role == "user"
    ):
        t_hr = time.perf_counter()
        prior = await _load_session_conversation(
            ctx["session_id"], ctx["agent_pk"], limit=_history_load_limit(ctx)
        )
        if prior:
            conversation = prior + conversation
            history_restore = {
                "mode": "server",
                "restored": len(prior),
                "ms": int((time.perf_counter() - t_hr) * 1000),
            }
    return conversation, history_restore


async def _memory_inputs(
    ctx: dict, impl: CustomAgent, user_id: str | None, user_text: str
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
    add_scope = {"user_id": user_id, "run_id": ctx["session_id"]}
    recall_scope = {**add_scope, "agent_id": ctx["ext_agent_id"]}
    consumes = impl.describe().consumes
    reads_memory = consumes is None or "memories" in consumes
    used_memory = (
        not ctx.get("ephemeral")  # 비영속(스펙 235): 회상·자동기록 전면 off(stateless)
        and reads_memory
        and memory.memory_enabled(ctx["memories"])
        and ctx["mem_cfg"] is not None
    )
    pipeline = ctx.get("nodes_resolved") is not None
    mem_hits = (
        await asyncio.to_thread(memory.search, recall_scope, user_text, ctx["mem_cfg"])
        if used_memory and not pipeline
        else []
    )
    memory_recalls: list[dict] = []
    mem_proxy = (
        _MemoryRecallProxy(recall_scope, ctx["mem_cfg"], user_text, memory_recalls)
        if (used_memory and pipeline)
        else None
    )
    return add_scope, recall_scope, used_memory, mem_hits, mem_proxy, memory_recalls


async def _build_turn_runtime(
    ctx: dict,
    impl: CustomAgent,
    principal: User | str,
    user_id: str | None,
    user_text: str,
    conversation: list[dict],
) -> dict:
    """그래프 빌드 재료(회상·창 프록시·도구·브로커·프롬프트) 준비 — 턴 상태 dict 반환."""
    (
        add_scope,
        recall_scope,
        used_memory,
        mem_hits,
        mem_proxy,
        memory_recalls,
    ) = await _memory_inputs(ctx, impl, user_id, user_text)
    pipeline = ctx.get("nodes_resolved") is not None
    # 단기 기억 창 프록시(스펙 270) — 노드형에만 주입. 전체 대화를 쥐고 노드별 depth로 슬라이스(현재 턴은
    # 그래프가 별도 시드하므로 프록시는 [:-1]로 분리). 기본 depth=에이전트 historyDepth(노드 미지정 시 상속).
    # 스펙 289 P1: 서버 재구성분 포함 conversation — 노드형도 첫 노드부터 이어진 대화 승계.
    history_windows: list[dict] = []
    hist_proxy = (
        _HistoryWindowProxy(_to_base_messages(conversation), ctx["history_depth"], history_windows)
        if pipeline
        else None
    )
    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(
        ctx["mcp_servers"], calls_sink, ctx.get("toolPolicy"), ctx.get("tool_names")
    )
    # 채팅 자가기록 도구는 제거됨(스펙 051) — agent_id 메모리는 어드민 저작 전용. 회상은 유지.
    # RAG 검색 도구 — vectorTables가 실 컬렉션으로 해석됐을 때만(스펙 037). 노드형은 컬렉션별 도구
    # 추가(스펙 268 P1 — _rag_tools_for).
    tools.extend(_rag_tools_for(ctx, calls_sink))
    # 회상된 기억은 prompt(시스템 프롬프트)에 합친다. 별도 system 메시지로 주입하면
    # create_agent의 system_prompt와 충돌해 모델 채팅 템플릿이 거부한다
    # ("System message must be at the beginning"). 단일 system 프롬프트 유지.
    prompt_prompt = ctx["prompt"]
    if mem_hits:
        # 브로커 memory 능력과 공유하는 포맷(스펙 104 drift 0) — 회상 텍스트 표현이 한 곳.
        recalled = memory.format_memory_hits(mem_hits)
        prompt_prompt = f"{prompt_prompt}\n\n# 관련 기억(회상됨)\n{recalled}"
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    # HIL 체크포인터(스펙 041). 있으면 위험 도구가 interrupt로 일시정지·재개될 수 있다. 없으면
    # 기존 무상태 동작(무회귀) — 단 위험 도구가 호출되면 interrupt가 예외로 새 fail-closed(미실행).
    # 비영속(스펙 235): 체크포인터 미부착 → 그래프 무상태 실행. **정정(스펙 237 실측)**: 체크포인터가
    # 없어도 interrupt 자체는 발생한다 — 승인 경로의 DB 쓰기는 _approval_frames의 ephemeral 게이트가
    # 막는다(여기만으론 불충분).
    ckpt = None if ctx.get("ephemeral") else checkpointer.get_checkpointer()
    # 능력 브로커(스펙 100) — 정책(에이전트 allowlist ∩ 유저 RBAC)으로 **미리 스코프**해 주입.
    # 로컬(ui) 실행 경로에만 준다: 원격 통째 프록시(_a2a_stream)는 broker 미주입(bypass 보존).
    # broker를 쓰는 flow(예: orchestrate)만 소비하고, 안 쓰면 무해(deny-by-default).
    # 스펙 256 v2: 루트 실행도 자기 id로 체인 시작 — 하위 어디서도 루트 재호출(순환) 불가.
    broker = build_broker(
        principal,
        ctx["capabilities"],
        ctx.get("toolPolicy"),
        ctx.get("rag_min_scores"),
        delegation_chain=((ctx.get("ext_agent_id"),) if ctx.get("ext_agent_id") else ()),
        delegation_budget={"n": 0},
    )
    # 노드 에이전트-호출 도구(스펙 318) — 노드형 노드가 `agent__{id}`로 다른 에이전트에 위임. broker
    # 경유라 재귀 가드·HIL·격리 승계(runtime.build_agent_tools). pipeline만(비노드형은 broker.discover
    # 경로라 도구 풀에 얹지 않는다 — 행위 보존). 후보=broker가 이미 스코프(권한 상승 0).
    if ctx.get("impl") == "pipeline":
        tools.extend(runtime.build_agent_tools(broker, await broker.agent_capabilities()))
    build_ctx = AgentBuildContext(
        prompt=prompt_prompt,
        model_cfg=ctx["model_cfg"],
        tools=tools,
        checkpointer=ckpt,
        params=run_params,
        memories=mem_hits,
        overrides=ctx.get("overrides"),
        broker=broker,
        memory_recall=mem_proxy,  # 노드별 캐싱 회상 프록시(스펙 268 P2) — 비노드형은 None(무회귀)
        history_window=hist_proxy,  # 단기 기억 창 프록시(스펙 270) — 비노드형은 None(에이전트 _window 경로 유지)
        # impl_config — 노코드 impl용 설정 통로. 노드형(259)=해석된 노드, 산출물형(190)=필드 명세.
        # 에이전트당 impl 하나라 상호배타(둘 중 해당하는 것만 실림, 그 외 impl은 무시).
        impl_config=(
            {"nodes": ctx["nodes_resolved"]}
            if ctx.get("nodes_resolved") is not None
            else ctx.get("artifact_spec")
        ),
    )
    return {
        "graph": impl.build_graph(build_ctx),
        "broker": broker,
        "tools": tools,
        "calls_sink": calls_sink,
        "pipeline": pipeline,
        "prompt_prompt": prompt_prompt,
        "add_scope": add_scope,
        "recall_scope": recall_scope,
        "used_memory": used_memory,
        "mem_hits": mem_hits,
        "memory_recalls": memory_recalls,
        "history_windows": history_windows,
    }


def _resolve_graph_entry(
    ctx: dict, body: ChatRequest, user_text: str
) -> tuple[str, Command | None, dict | None]:
    """산출물 pending 재개/새 thread 결정(스펙 188) — 반환 (thread_id, graph_input, pending_artifact).
    graph_input=None이면 새 실행(호출측이 {"messages": seed}로 채움).

    thread_id는 **턴별 고유**(세션-안정 아님): 세션-안정으로 두고 매 턴 전체 히스토리를 넘기면
    체크포인트의 add_messages 리듀서가 메시지를 중복 누적한다(무상태 윈도잉과 충돌). 턴마다 새
    thread를 만들어 그 턴의 일시정지/재개에만 쓰고, Approval.checkpoint에 박아 재개 키로 삼는다.
    산출물형 ask/form 대기(스펙 188)면 **그 thread를 이어** Command(resume=union 봉투)로 재개한다
    (새 실행 금지 — produce의 기록된 답 리플레이가 그 체크포인트에 있다). pop = 재개 시도는 1회.
    이중 입력 일급: 폼 대기 중이라도 텍스트가 오면 {"type":"text"}로 재개(병합은 뼈대 ctx.form 소유)."""
    pending_artifact = _PENDING_ARTIFACT.pop(ctx["session_id"], None)
    if body.form is not None and (
        pending_artifact is None or body.form.formId != pending_artifact.get("form_id")
    ):
        # 폼 제출인데 대응 pending이 없거나 formId 불일치(스테일/위조/재시작 소실) — 조용히 텍스트로
        # 오인하지 않고 명시적으로 거절(fail-closed). pending은 원복(유효한 폼이 남아 있으면 재사용).
        if pending_artifact is not None:
            _PENDING_ARTIFACT[ctx["session_id"]] = pending_artifact
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
        thread_id = f"{ctx['ext_agent_id']}:{ctx['session_id']}:{secrets.token_hex(4)}"
        graph_input = None
    return thread_id, graph_input, pending_artifact


def _turn_config(
    ctx: dict, thread_id: str, user_id: str | None, capture: trace_capture.TraceCaptureHandler
) -> dict:
    """LangGraph 실행 config — 관측 콜백(스펙 118)·실측 캡처(스펙 205) 부착."""
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    # 관측(스펙 118→328) — OTEL이 설정됐을 때만 콜백 부착(미설정=무동작). 핵심 채팅 경로 무영향.
    # 비영속(스펙 235): 외부 관측 기록도 스킵(고트래픽·기록 무의미 계약 — 앱 DB 밖이라도 적재 안 함).
    if not ctx.get("ephemeral"):
        config = observability.with_trace(
            config,
            name=f"chat:{ctx['ext_agent_id']}",
            session_id=ctx["session_id"],
            user_id=user_id,
        )
    # 실측 캡처(스펙 205) — 모델 호출 메시지·usage. OTEL 콜백과 병행(둘 다 callbacks 리스트).
    config["callbacks"] = [*list(config.get("callbacks") or []), capture]
    return config


def _seed_and_sent(
    conversation: list[dict], ctx: dict, pipeline: bool, prompt_prompt: str
) -> tuple[list[dict], list[dict], list[dict]]:
    """윈도 절단·전송 전문·그래프 시드 — 반환 (messages, sent_messages, seed_messages).

    실행 컨텍스트를 historyDepth로 절단(최근 N개만 모델에 전달). 스펙 289 P1: 원천=conversation
    (서버 모드면 DB 재구성분 포함) — 절단 규칙은 동일. 전송 프롬프트 전문(스펙 131)은 실제 그래프
    입력을 캡·마스킹해 캡처. 노드형(스펙 270): 대화를 히스토리 프록시가 노드별 depth로 슬라이스하므로
    그래프엔 **현재 턴만** 시드(이전 대화는 프록시가 각 노드에 주입). 비노드형은 윈도된 전체를 그대로
    시드(무회귀). sent_messages는 에이전트-레벨 뷰로 유지(상속 노드=동일 집합, 커스텀 depth는 node
    timeline 192·historyWindows로 관측)."""
    messages = _window(conversation, ctx["history_depth"])
    sent_messages = _build_sent_messages(prompt_prompt, messages)
    seed_messages = messages[-1:] if (pipeline and messages) else messages
    return messages, sent_messages, seed_messages


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
    ctx: dict,
    turn: dict,
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
        "promptRef": ctx["ext_agent_id"],
        "memories": turn["mem_hits"],
        "mcp": turn["calls_sink"],
        "graph": observed,
        "artifact": awaiting,
        **(
            {
                "agentVersion": ctx["exec_version"],
                **({"versionPinned": True} if ctx.get("pinned_version") else {}),
            }
            if ctx.get("exec_version")
            else {}
        ),
        "sentMessages": sent_messages,
    }


async def _ask_frames(
    ctx: dict,
    interrupted: dict,
    turn: dict,
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
    _PENDING_ARTIFACT[ctx["session_id"]] = {
        "thread_id": thread_id,
        "version": ctx.get("pinned_version"),
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
        ctx["persist_history"],
        user_id=user_id,
        turn_id=thread_id,
    )
    yield _mid_frame(mid)  # 스펙 209 P1.5
    yield f"event: trace\ndata: {json.dumps(ask_trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


async def _form_frames(
    ctx: dict,
    interrupted: dict,
    turn: dict,
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
    _PENDING_ARTIFACT[ctx["session_id"]] = {
        "thread_id": thread_id,
        "kind": "form",
        "form_id": form_id,
        "fields": form_fields,
        "version": ctx.get("pinned_version"),  # 재개 턴 버전 승계(codex 242 #1)
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
        ctx["persist_history"],
        user_id=user_id,
        turn_id=thread_id,
    )
    yield _mid_frame(mid)  # 스펙 209 P1.5
    yield f"event: trace\ndata: {json.dumps(form_trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


def _pending_approval_trace(
    ctx: dict,
    turn: dict,
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
        "promptRef": ctx["ext_agent_id"],
        "memories": turn["mem_hits"],
        "mcp": turn["calls_sink"],
        "graph": [],
        "approval": {"id": apid, "action": action, "status": "pending"},
        **({"agentVersion": ctx["exec_version"]} if ctx.get("exec_version") else {}),
    }
    # 승인대기 턴도 회상 조회 이력 일관 노출(스펙 079).
    if turn["used_memory"]:
        pending_trace["memoryQuery"] = user_text[:300]
    if turn["broker"].invocations:
        # 일시정지 **이전에 이미 실행된** 선행 브로커 호출 표면화(스펙 130, codex #2).
        pending_trace["brokerCalls"] = _broker_calls_trace(turn["broker"].invocations)
    if turn["history_windows"]:
        # 일시정지 이전 carry 노드가 이미 기록한 단기 기억 창 표면화(codex 270 Low — 관측 일관).
        pending_trace["historyWindows"] = turn["history_windows"]
    pending_trace["sentMessages"] = sent_messages  # 승인대기 턴도 전송 전문(스펙 131)
    ov_trace_p = _overrides_trace(ctx.get("overrides"), ctx.get("overrides_nodes_status"))
    if ov_trace_p:
        pending_trace["overrides"] = ov_trace_p  # 스펙 134
    if ctx["rag_collections"]:
        pending_trace["ragCollections"] = [c["name"] for c in ctx["rag_collections"]]
    return pending_trace


async def _approval_frames(
    ctx: dict,
    interrupted: dict,
    turn: dict,
    *,
    thread_id: str,
    user_id: str | None,
    user_text: str,
    t0: float,
    sent_messages: list[dict],
) -> AsyncIterator[str]:
    """위험 도구가 그래프를 멈췄다 → 런타임 Approval 생성 + "대기" 프레임 후 종료(정상 턴 영속 안 함).
    부수효과(canned·calls_sink)는 interrupt 이전이라 0 — 승인 전 무실행 불변식(스펙 041 §3.3)."""
    if ctx.get("pinned_version"):
        # 버전 미리보기(스펙 242) — 승인 재개는 서빙 config로 돌아 버전이 어긋난다(drift).
        # Approval을 만들지 않고 명시 안내(235 비영속 게이트와 동형). 도구는 interrupt 이전이라 미실행.
        yield f"data: {json.dumps({'error': '버전 미리보기에서는 승인이 필요한 도구를 사용할 수 없습니다 — 활성 버전에서 실행하거나 승인 없는 도구를 사용하세요.'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
        return
    if ctx.get("ephemeral"):
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
    ctx: dict,
    interrupts: list[dict],
    turn: dict,
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


def _annotate_execution(
    trace: dict,
    ctx: dict,
    turn: dict,
    *,
    capture: trace_capture.TraceCaptureHandler,
    sent_messages: list[dict],
    impl: CustomAgent,
) -> None:
    """실행 메타 주석 — 버전(242)·도구 무발동 진단(236)·전송 전문 출처(205/131)."""
    if ctx.get("exec_version"):
        # 실행 버전(스펙 242) — 이 턴이 어느 버전 config였나(지정 버전 미리보기 포함, 240 평가 귀속과 대칭).
        trace["agentVersion"] = ctx["exec_version"]
        if ctx.get("pinned_version"):
            trace["versionPinned"] = True  # 미리보기 턴 표식(활성 아님)
    # 도구 무발동 진단(스펙 236) — 도구가 바인딩된 턴의 호출 수를 항상 기록. called=0이면 UI가
    # "왜 안 되는지" 후보(모델이 도구 호출 미지원(mock 등)·질문이 도구와 무관)를 표면화한다
    # (158 회상·125 검색 진단의 결 — 조용한 무발동 금지). impl이 도구 표면(mcps/vectorTables)을
    # 안 읽는 타입(route·artifact류)은 제외 — 그건 무발동이 아니라 설계상 무소비(폼이 이미 경고).
    consumes = impl.describe().consumes
    reads_tools = consumes is None or bool({"mcps", "vectorTables"} & set(consumes))
    if turn["tools"] and reads_tools:
        trace["toolDiag"] = {
            "bound": [getattr(tl, "name", "?") for tl in turn["tools"]][:20],
            "called": len(turn["calls_sink"]),
        }
    # 전송 프롬프트(스펙 205): 콜백 실측(마지막 모델 호출 — 커스텀 impl의 계획·도구 안내 포함)
    # 우선, 콜백 미발화면 기존 재구성(131) 폴백. 출처를 표기해 UI가 정직하게 라벨링.
    if capture.calls:
        trace["sentMessages"] = _format_sent_measured(capture.calls[-1])
        trace["modelCalls"] = len(capture.calls)
        trace["sentMessagesSource"] = "measured"
    else:
        trace["sentMessages"] = sent_messages  # 전송 프롬프트 전문(스펙 131, 메시지당 2000자 캡)
        trace["sentMessagesSource"] = "reconstructed"


def _annotate_context_sources(
    trace: dict, ctx: dict, turn: dict, *, user_text: str, history_restore: dict | None
) -> None:
    """맥락 출처 주석 — 오버라이드(134)·재구성 실측(289)·브로커(130)·RAG(037)·메모리(079/268/270)."""
    ov_trace = _overrides_trace(ctx.get("overrides"), ctx.get("overrides_nodes_status"))
    if ov_trace:
        # 이 턴에 적용된 오버라이드(스펙 134) — 세션에 설정 다른 턴이 섞여도 턴별 구분 가능.
        trace["overrides"] = ov_trace
    if history_restore:
        # 히스토리 서버 재구성 실측(스펙 289 P1) — 몇 개를 몇 ms에 이어붙였나(캐시 재론의 근거 데이터).
        trace["historyRestore"] = history_restore
    if turn["broker"].invocations:
        # 브로커 호출 상세(스펙 130) — 조율형의 RAG 검색이 인스펙터에 "N건·최고 유사도"로 보이게.
        # 위임 없던 턴은 필드 자체가 없음(무회귀).
        trace["brokerCalls"] = _broker_calls_trace(turn["broker"].invocations)
    if ctx["rag_collections"]:
        # 구성된 RAG 컬렉션 — 호출 안 해도 인스펙터에 노출(실제 호출은 trace["mcp"]의 server="rag").
        trace["ragCollections"] = [c["name"] for c in ctx["rag_collections"]]
    if ctx.get("rag_unresolved"):
        # 요청됐으나 해석 실패한 이름 — 도구가 조용히 비는 footgun을 인스펙터에 드러냄(타자검증 F).
        trace["ragUnresolved"] = ctx["rag_unresolved"]
    _annotate_memory_observations(trace, turn, user_text=user_text)


def _annotate_memory_observations(trace: dict, turn: dict, *, user_text: str) -> None:
    """메모리 관측 주석 — 회상 스코프/쿼리(079)·노드별 회상(268 P2)·단기 기억 창(270)."""
    if turn["used_memory"]:
        # None이 아닌 회상 축만 — {"user_id","run_id","agent_id"} 부분집합 (Inspector가 축별 렌더).
        trace["memoryScope"] = {k: v for k, v in turn["recall_scope"].items() if v}
        # 회상에 쓴 쿼리(=user_text)를 에코 — 0건 회상이어도 "조회 행위"를 인스펙터에 남긴다(스펙 079).
        # 표시 전용·길이상한(방금 그 유저가 보낸 텍스트라 경계 이동 없음).
        trace["memoryQuery"] = user_text[:300]
    if turn["memory_recalls"]:
        # 노드별 회상 기록(스펙 268 P2) — (node, query, hits, cached). 프록시가 조회마다 남김
        # (082 조회 행위 계측). 인스펙터가 노드 행에 귀속 렌더.
        trace["memoryRecalls"] = turn["memory_recalls"]
    if turn["history_windows"]:
        # 노드별 단기 기억 창 기록(스펙 270) — (node, depth, count). 프록시가 첫 진입에 남김
        # (082 조회 계측). 내용 아닌 건수만(누출 0). 인스펙터가 노드 행에 귀속 렌더.
        trace["historyWindows"] = turn["history_windows"]


def _final_trace(
    ctx: dict,
    turn: dict,
    *,
    capture: trace_capture.TraceCaptureHandler,
    full: str,
    total_ms: int,
    messages: list[dict],
    sent_messages: list[dict],
    observed: list,
    impl: CustomAgent,
    user_text: str,
    history_restore: dict | None,
) -> tuple[dict, dict]:
    """정상/오류 종결 턴의 trace·tokens 조립 — 반환 (trace, tokens)."""
    prompt_chars = sum(len(m["content"]) for m in messages)
    # 토큰(스펙 205): 모델 usage 실측 우선, 부재 시 추정 폴백(estimated로 정직 표기).
    if capture.usage_seen:
        tokens = {"in": capture.tokens_in, "out": capture.tokens_out, "estimated": False}
    else:
        tokens = {**runtime.estimate_tokens(prompt_chars, len(full)), "estimated": True}
    trace = runtime.assemble_trace(
        agent_id=ctx["ext_agent_id"],
        memories=turn["mem_hits"],
        mcp_calls=turn["calls_sink"],
        used_memory=turn["used_memory"],
        total_ms=total_ms,
        tokens=tokens,
        graph_observations=observed,
    )
    trace["contextMessages"] = len(messages)  # 모델에 넣은 메시지 수(historyDepth 적용 결과)
    _annotate_execution(trace, ctx, turn, capture=capture, sent_messages=sent_messages, impl=impl)
    _annotate_context_sources(
        trace, ctx, turn, user_text=user_text, history_restore=history_restore
    )
    return trace, tokens


# 백그라운드 자동 기억 저장 태스크 참조(스펙 314) — 스트림(제너레이터)이 끝나거나 클라이언트가 떠나도
# 태스크가 GC/취소되지 않도록 강참조를 유지. 완료 시 콜백으로 스스로 제거한다.
_BG_MEMORY_TASKS: set[asyncio.Task] = set()
_MEMORY_SAVE_ITEM_CAP = 20  # 트레일링 이벤트/트레이스에 실을 기억 항목 상한
_MEMORY_SAVE_TEXT_CAP = 300  # 항목 본문 표시 상한(마스킹 후, 131/191 프레임 재사용)
_MEMORY_ADD_TIMEOUT_S = (
    30  # 백그라운드 저장(mem0 LLM 추출) 대기 상한 — 초과 시 pending만 해제(codex P1)
)
_TRAILING_EVENT_TIMEOUT_S = (
    60  # 트레일링 이벤트 대기 상한 — 연결 무한 보유 방지(태스크는 계속, codex P1)
)


def _summarize_saved(saved: list[dict]) -> dict:
    """백그라운드 기억 저장 결과를 인스펙터 표시용으로 정화(스펙 314) — 비밀 마스킹+캡. status:
    ok(1건+)/none(0건). count=원 건수(상한 전). items=[{event, text(마스킹)}]. event도 마스킹
    (codex P2: 백엔드 계약상 event는 '원문'이라 custom 백엔드가 secret-like 값을 넣을 수 있음)."""
    items: list[dict] = []
    for row in (saved or [])[:_MEMORY_SAVE_ITEM_CAP]:
        text = memory._sanitize(row.get("text", ""), cap=_MEMORY_SAVE_TEXT_CAP)
        if not text:
            continue
        items.append(
            {"event": memory._sanitize(str(row.get("event") or "ADD"), cap=16), "text": text}
        )
    return {"status": "ok" if items else "none", "count": len(saved or []), "items": items}


async def _finalize_memory_trace(mid: str, summary: dict) -> None:
    """저장 완료 후 그 assistant 메시지의 영속 trace에 memorySaved 병합(스펙 314) — 새로고침 시
    인스펙터가 결과를 다시 불러오게 한다. 잘못된/사라진/비-assistant mid는 no-op(codex P2 — 함수
    자체가 '남의 메시지 클로버 금지'를 보장하도록 role까지 확인)."""
    try:
        pk = uuid.UUID(mid)
    except (ValueError, TypeError):
        return
    async with SessionLocal() as db:
        msg = await db.get(Message, pk)
        if msg is None or msg.role != "assistant" or not isinstance(msg.trace, dict):
            return
        trace = dict(
            msg.trace
        )  # 새 dict 대입으로 JSON 컬럼 dirty 플래그 확실히(in-place 변형 아님)
        trace["memorySaved"] = summary
        msg.trace = trace
        await db.commit()


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


async def _final_frames(
    ctx: dict,
    turn: dict,
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
    for inv in turn["broker"].invocations:
        observed.append({"node": inv["node"], "ms": inv.get("ms", 0)})
    full = "".join(acc)
    total_ms = int((time.perf_counter() - t0) * 1000)
    # 오류 턴은 영속/메모리 저장하지 않는다 (부분/실패 응답 오염 방지).
    will_add_memory = (not errored) and turn["used_memory"] and bool(full)
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
            ctx["persist_history"],
            user_id=user_id,
            turn_id=thread_id,
        )
    if mid:
        yield _mid_frame(mid)  # 스펙 209 P1.5 — 피드백 부착용 assistant id
    # P0(codex): 저장 태스크를 done을 yield하기 **전에** 띄운다. done 직후 클라이언트가 끊어(제너레이터
    # 취소) yield 이후 코드가 재개되지 않아도, 태스크는 이미 생성·등록·detached라 끝까지 완료된다
    # (저장·영속 보장). yield 뒤에 만들면 취소 시 태스크 자체가 안 생겨 저장이 유실된다.
    task = None
    live_trace = trace
    if will_add_memory:
        task = asyncio.ensure_future(
            _bg_memory_add(turn["add_scope"], user_text, full, ctx["mem_cfg"], mid)
        )
        _BG_MEMORY_TASKS.add(task)  # 강참조 유지(GC/취소 방지) — 완료 콜백이 스스로 제거
        task.add_done_callback(_BG_MEMORY_TASKS.discard)
        # memoryPending은 **라이브 스트림에만**·**mid 있을 때만** 싣는다 — mid 없으면(persistHistory=false)
        # 완료 이벤트로 조용히 해제할 방법이 없어(mid로 패치) 스피너가 안 풀린다(codex P1).
        if mid:
            live_trace = {**trace, "memoryPending": True}
    # 스펙 314: 답변+trace+done을 **먼저** 흘려 '처리 중'을 즉시 해제한다. 무거운 자동 기억 저장(mem0 LLM
    # 추출 — 초 단위)은 위 백그라운드 태스크가 담당. 이게 done 앞을 막던 게 지연의 원인이었다.
    yield f"event: trace\ndata: {json.dumps(live_trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"
    if task is not None and mid:
        # 완료를 기다려 트레일링 이벤트로 조용히 알린다(status 무관 — none/error도 pending 해제용).
        # shield로 클라이언트 취소로부터 태스크를 보호하고, wait_for로 대기 상한을 둬 저장이 비정상적으로
        # 오래 걸려도 연결을 무한정 붙들지 않는다(codex P1 — 태스크는 계속 완료돼 영속 trace를 갱신하므로
        # 새로고침 시 반영). 취소(클라이언트 이탈)는 재전파해 제너레이터를 정리한다.
        try:
            summary = await asyncio.wait_for(
                asyncio.shield(task), timeout=_TRAILING_EVENT_TIMEOUT_S
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # TimeoutError 포함 — 트레일링 이벤트만 생략(태스크·영속은 계속)
            summary = None
        if summary is not None:
            yield (
                "event: memory\n"
                f"data: {json.dumps({'mid': str(mid), 'memorySaved': summary}, ensure_ascii=False)}\n\n"
            )


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
    # 머신 토큰("machine" 센티넬)이면 None → 세션 단기 폴백(기존 "빈 userId" 동작과 동일, 무회귀).
    user_id = None if isinstance(principal, str) else str(principal.id)

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
    graph = turn["graph"]
    thread_id, graph_input, pending_artifact = _resolve_graph_entry(ctx, body, user_text)
    capture = trace_capture.TraceCaptureHandler()
    config = _turn_config(ctx, thread_id, user_id, capture)
    messages, sent_messages, seed_messages = _seed_and_sent(
        conversation, ctx, turn["pipeline"], turn["prompt_prompt"]
    )

    # interrupt 수집 리스트를 **턴 스코프로 끌어올린다**(스펙 346, codex P1): 관문(아래 event_stream의
    # finally)이 "그래프가 멈춘 채인가"를 알아야 한다. 승인 행 커밋·폼 포인터 등록은 interrupt보다
    # **나중**이라, 그 사이 취소되면 핀이 아직 없다 — 이 리스트가 유일한 증거다.
    interrupts: list[dict] = []

    async def _run_turn() -> AsyncIterator[str]:
        t0 = time.perf_counter()
        yield f"data: {json.dumps({'session': ctx['session_id']}, ensure_ascii=False)}\n\n"
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
                _PENDING_ARTIFACT[ctx["session_id"]] = pending_artifact
            # 연결 실패로 보이면 'Mock LLM' 전환 힌트를 덧붙인다(스펙 058 G4). 그 외 오류는 원문 유지.
            hint = _model_error_hint(exc, ctx.get("model_cfg"))
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
