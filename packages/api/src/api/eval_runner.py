"""평가 실행 러너 — 오염 제로 에이전트 턴 + 관측 union (스펙 137 단계 ②).

`chat()` 재사용은 불가(persistHistory=False여도 세션 lazy-create·turns 갱신·자동 memory.add가
발생 — 137 조사 확정). 이 러너는 `stream_local_reply`(A2A 서빙용 순수 컴퓨트) 골격에
`event_stream`의 **관측 수집부**(updates 노드·calls_sink·broker invocations)를 이식하고
**build_broker를 주입**(조율형 위임 채점 지원 — stream_local_reply엔 없어 위임이 안 돌았음)한다.
`_persist`·`memory.add`는 절대 호출하지 않는다(오염 제로). 메모리 **회상(search)은 수행** —
읽기 전용이라 무오염이며, 직접형의 memory 사용 채점(`memory:used` 토큰)의 근거가 된다.
checkpointer=None — HIL 게이트 cap은 interrupt가 예외로 떨어져 error 관측(평가 중 승인 대기 없음).

관측 union(조사 확정 — 없으면 직접형 도구 사용을 놓쳐 "조용한 초록", 회고 100 대죄):
  trace_nodes = 그래프 노드(원형) ∪ 브로커 canonical(broker_invoke: 접두 제거형 병기)
              ∪ 직접형 calls_sink(`mcp:{server}/{tool}`, rag는 `rag:{tool}`) ∪ `memory:used`.
→ `trace_has("rag:")` 같은 assert가 직접형/조율형 무관하게 채점된다.
"""

import asyncio
import logging
import uuid
from typing import Any

from agent.runtime import AgentBuildContext, AgentConfigError, CustomAgent

from . import memory, observability, runtime
from .broker import build_broker
from .broker.core import PolicyScopedBroker
from .chat import _load_context, _window, resolve_agent_runtime
from .models import User

log = logging.getLogger("api.eval")

_OUTPUT_CAP = 4000  # obs 영속 시 출력 캡(성적표 표시용 — 전문 아님)


def _canonical_tokens(
    observed_nodes: list[str],
    calls_sink: list[dict],
    broker_invocations: list[dict],
    used_memory: bool,
) -> list[str]:
    """관측 3형태를 canonical 토큰으로 union — 채점 어휘를 에이전트 형태와 무관하게 통일."""
    tokens: list[str] = list(observed_nodes)
    for inv in broker_invocations:
        node = str(inv.get("node", ""))
        tokens.append(node)
        if node.startswith("broker_invoke:"):
            tokens.append(node[len("broker_invoke:") :])  # canonical: rag:X / mcp:s/t / memory:user
    for call in calls_sink:
        server = str(call.get("server", ""))
        tool = str(call.get("tool", ""))
        tokens.append(f"rag:{tool}" if server == "rag" else f"mcp:{server}/{tool}")
    if used_memory:
        tokens.append("memory:used")
    return tokens


async def _recall_memory(ctx: dict, user_text: str) -> tuple[bool, list, str]:
    """메모리 회상(읽기 전용 — 무오염) → (used_memory, mem_hits, persona_prompt). add는 절대 안 함."""
    used_memory = memory.memory_enabled(ctx["memories"]) and ctx["mem_cfg"] is not None
    recall_scope = {"user_id": None, "run_id": None, "agent_id": ctx["ext_agent_id"]}
    mem_hits = (
        await asyncio.to_thread(memory.search, recall_scope, user_text, ctx["mem_cfg"])
        if used_memory
        else []
    )
    persona_prompt = ctx["persona"]
    if mem_hits:
        persona_prompt = (
            f"{persona_prompt}\n\n# 관련 기억(회상됨)\n{memory.format_memory_hits(mem_hits)}"
        )
    return used_memory, mem_hits, persona_prompt


async def _build_eval_graph(
    ctx: dict,
    impl: CustomAgent,
    persona_prompt: str,
    mem_hits: list,
    calls_sink: list[dict],
    principal: User | str,
    delegation_chain: tuple,
    delegation_budget: dict | None,
) -> tuple[Any, PolicyScopedBroker]:
    """평가용 그래프를 도구·브로커 주입으로 빌드 → (graph, broker)."""
    tools = await runtime.build_mcp_tools(
        ctx["mcp_servers"], calls_sink, ctx.get("toolPolicy"), ctx.get("tool_names")
    )
    if ctx["rag_collections"]:
        tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink))
    # 브로커 주입(조율형 위임 채점) — 실행 주체(principal)의 RBAC로 스코프(chat 경로와 동일 술어).
    # 스펙 256 v2(깊이 N): 호출 체인에 자기 자신을 덧붙여 하위 브로커에 관통 — 체인 내 재방문만
    # 차단(순환 0), 새 에이전트로는 계속 하강 가능.
    chain = tuple(delegation_chain) + ((ctx["ext_agent_id"],) if ctx.get("ext_agent_id") else ())
    broker = build_broker(
        principal,
        ctx["capabilities"],
        ctx.get("toolPolicy"),
        delegation_chain=chain,
        delegation_budget=delegation_budget,
    )
    # 노드 에이전트-호출 도구(스펙 318) — 평가도 실제 파이프라인(위임 포함)을 태운다(317 입구 정합).
    # pipeline만·broker가 이미 스코프(권한 상승 0).
    if ctx.get("impl") == "pipeline":
        tools.extend(runtime.build_agent_tools(broker, await broker.agent_capabilities()))
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    build_ctx = AgentBuildContext(
        persona=persona_prompt,
        model_cfg=ctx["model_cfg"],
        tools=tools,
        checkpointer=None,  # HIL cap은 fail-closed(interrupt→예외→error 관측)
        params=run_params,
        memories=mem_hits,
        broker=broker,
        # impl_config — 노코드 impl 설정 통로(codex 317 P1: eval 입구 누락 봉합). 이게 없으면 노드형/
        # 산출물형 평가가 **기본 단일 노드로 조용히 퇴화**해 실제 서빙과 다른 것을 채점했고, 미등록
        # 코드 노드도 설정 오류 대신 폴백 실행됐다. 채팅·A2A 서빙·승인 재개와 동일 주입(네 번째 입구).
        impl_config=(
            {"nodes": ctx["nodes_resolved"]}
            if ctx.get("nodes_resolved") is not None
            else ctx.get("artifact_spec")
        ),
    )
    return impl.build_graph(build_ctx), broker


async def _stream_observed(
    graph: Any, messages: list[dict], cfg: dict
) -> tuple[str, list[str], bool, str | None]:
    """그래프 스트림 실행 + 관측 수집 → (output, observed_nodes, error, detail)."""
    acc: list[str] = []
    observed_nodes: list[str] = []
    error = False
    detail = None
    try:
        async for stream_mode, chunk in graph.astream(
            {"messages": messages}, config=cfg, stream_mode=["messages", "updates"]
        ):
            if stream_mode == "messages":
                msg_chunk, _meta = chunk
                if runtime.is_tool_message(msg_chunk):
                    continue
                text = runtime._content_text(getattr(msg_chunk, "content", ""))
                if text:
                    acc.append(text)
            elif stream_mode == "updates" and isinstance(chunk, dict):
                if "__interrupt__" in chunk:
                    # 승인 게이트 cap — 평가에선 진행 불가(fail-closed 관측).
                    error = True
                    detail = "승인 게이트 도구가 호출됨 — 평가 실행은 승인 없이 중단(fail-closed)"
                observed_nodes.extend(n for n in chunk if not n.startswith("__"))
    except Exception as exc:
        error = True
        detail = str(exc)[:500]
    return "".join(acc), observed_nodes, error, detail


async def eval_run_agent(
    agent_pk: uuid.UUID,
    user_text: str,
    principal: User | str,
    overrides: dict | None = None,
    version: str | None = None,
    delegation_chain: tuple = (),
    delegation_budget: dict | None = None,
) -> dict:
    """케이스 1건 실행 → obs {"output", "trace_nodes", "error", "detail"?}.

    overrides(스펙 141): 모델 비교 실행용 — 기존 화이트리스트 경로(_load_context)를 그대로 태워
    {"model": 레지스트리 이름}만 주입한다(admin 내부 호출이라 own=None 특권 경로).
    실패(설정 오류·모델 예외·HIL interrupt)는 예외를 던지지 않고 error=True obs로 접는다 —
    run_eval이 no_error assert로 채점하고 전체 평가는 계속(하네스 계약)."""
    try:
        ctx = await _load_context(
            agent_pk, None, overrides, version=version
        )  # 버전 지정 평가(스펙 242)
    except Exception as exc:
        return {
            "output": "",
            "trace_nodes": [],
            "error": True,
            "detail": f"컨텍스트 로드 실패: {exc}",
        }
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as exc:
        return {"output": "", "trace_nodes": [], "error": True, "detail": f"런타임 미해결: {exc}"}
    if impl is None or ctx["model_cfg"] is None:
        return {
            "output": "",
            "trace_nodes": [],
            "error": True,
            "detail": "로컬(ui) 에이전트가 아니거나 채팅 모델이 없습니다(평가는 로컬 에이전트만)",
        }

    used_memory, mem_hits, persona_prompt = await _recall_memory(ctx, user_text)

    calls_sink: list[dict] = []
    try:
        graph, broker = await _build_eval_graph(
            ctx,
            impl,
            persona_prompt,
            mem_hits,
            calls_sink,
            principal,
            delegation_chain,
            delegation_budget,
        )
    except AgentConfigError as exc:
        # 그래프 조립 시점 설정 실패(스펙 317 — 코드 노드 impl 미등록 등)도 error obs로 접는다
        # (하네스 계약 — 케이스 error 채점, 전체 평가는 계속. 조용한 폴백 채점 금지).
        return {"output": "", "trace_nodes": [], "error": True, "detail": f"그래프 조립 실패: {exc}"}
    messages = _window([{"role": "user", "content": user_text}], ctx["history_depth"])
    cfg = observability.with_trace(None, name=f"eval:{ctx['ext_agent_id']}")

    output, observed_nodes, error, detail = await _stream_observed(graph, messages, cfg)

    return {
        "output": output[:_OUTPUT_CAP],
        "trace_nodes": _canonical_tokens(
            observed_nodes, calls_sink, broker.invocations, used_memory
        ),
        "error": error,
        **({"detail": detail} if detail else {}),
    }


async def eval_run_rag(collection: dict, query: str) -> dict:
    """RAG 컬렉션 평가 1건(스펙 140) — rag.py 시험 엔드포인트와 같은 공유 코어(search_collections)로
    검색만 수행(읽기 전용 — 오염 자명 제로). obs["rag"]에 hits/top_score를 실어 rag 전용 assert가
    채점한다. 실패는 error obs(fail-closed)."""
    try:
        hits = await runtime.search_collections([collection], query, top_k=4)
    except runtime.RagSearchError as exc:
        return {
            "output": "",
            "trace_nodes": [f"rag:{collection.get('name', '')}"],
            "error": True,
            "detail": exc.tool_msg,
            "rag": {"hits": [], "top_score": None},
        }
    return {
        "output": runtime.format_rag_hits(hits)[:_OUTPUT_CAP],
        "trace_nodes": [f"rag:{collection.get('name', '')}"],
        "error": False,
        "rag": {
            "hits": [
                # meta는 엔티티 컬렉션의 행별 metadata(스펙149) — rag_meta_contains 판정이 읽는다(스펙310).
                # 문서형 hit는 meta=None. 버리지 말고 실어 보낸다(전엔 score/filename/text만 남겨 판정 불가).
                {
                    "score": h["score"],
                    "filename": h["filename"],
                    "text": h["text"][:300],
                    "meta": h.get("meta"),
                }
                for h in hits
            ],
            "top_score": hits[0]["score"] if hits else None,
        },
    }
