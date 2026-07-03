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

from agent.runtime import AgentBuildContext, AgentConfigError

from . import memory, observability, runtime
from .broker import build_broker
from .chat import _load_context, _window, resolve_agent_runtime

log = logging.getLogger("api.eval")

_OUTPUT_CAP = 4000  # obs 영속 시 출력 캡(성적표 표시용 — 전문 아님)


def _canonical_tokens(observed_nodes: list[str], calls_sink: list[dict], broker_invocations: list[dict], used_memory: bool) -> list[str]:
    """관측 3형태를 canonical 토큰으로 union — 채점 어휘를 에이전트 형태와 무관하게 통일."""
    tokens: list[str] = list(observed_nodes)
    for inv in broker_invocations:
        node = str(inv.get("node", ""))
        tokens.append(node)
        if node.startswith("broker_invoke:"):
            tokens.append(node[len("broker_invoke:"):])  # canonical: rag:X / mcp:s/t / memory:user
    for c in calls_sink:
        server = str(c.get("server", ""))
        tool = str(c.get("tool", ""))
        tokens.append(f"rag:{tool}" if server == "rag" else f"mcp:{server}/{tool}")
    if used_memory:
        tokens.append("memory:used")
    return tokens


async def eval_run_agent(agent_pk, user_text: str, principal) -> dict:
    """케이스 1건 실행 → obs {"output", "trace_nodes", "error", "detail"?}.

    실패(설정 오류·모델 예외·HIL interrupt)는 예외를 던지지 않고 error=True obs로 접는다 —
    run_eval이 no_error assert로 채점하고 전체 평가는 계속(하네스 계약)."""
    try:
        ctx = await _load_context(agent_pk, None)
    except Exception as exc:  # noqa: BLE001 — 미존재 에이전트 등
        return {"output": "", "trace_nodes": [], "error": True, "detail": f"컨텍스트 로드 실패: {exc}"}
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as exc:
        return {"output": "", "trace_nodes": [], "error": True, "detail": f"런타임 미해결: {exc}"}
    if impl is None or ctx["model_cfg"] is None:
        return {"output": "", "trace_nodes": [], "error": True,
                "detail": "로컬(ui) 에이전트가 아니거나 채팅 모델이 없습니다(평가는 로컬 에이전트만)"}

    # 메모리 회상(읽기 전용 — 무오염). add는 절대 안 함.
    used_memory = memory.memory_enabled(ctx["memories"]) and ctx["mem_cfg"] is not None
    recall_scope = {"user_id": None, "run_id": None, "agent_id": ctx["ext_agent_id"]}
    mem_hits = (
        await asyncio.to_thread(memory.search, recall_scope, user_text, ctx["mem_cfg"])
        if used_memory
        else []
    )
    persona_prompt = ctx["persona"]
    if mem_hits:
        persona_prompt = f"{persona_prompt}\n\n# 관련 기억(회상됨)\n{memory.format_memory_hits(mem_hits)}"

    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(ctx["mcp_servers"], calls_sink)
    if ctx["rag_collections"]:
        tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink))
    # 브로커 주입(조율형 위임 채점) — 실행 주체(principal)의 RBAC로 스코프(chat 경로와 동일 술어).
    broker = build_broker(principal, ctx["capabilities"])
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    build_ctx = AgentBuildContext(
        persona=persona_prompt,
        model_cfg=ctx["model_cfg"],
        tools=tools,
        checkpointer=None,  # HIL cap은 fail-closed(interrupt→예외→error 관측)
        params=run_params,
        memories=mem_hits,
        broker=broker,
    )
    graph = impl.build_graph(build_ctx)
    messages = _window([{"role": "user", "content": user_text}], ctx["history_depth"])
    cfg = observability.with_trace(None, name=f"eval:{ctx['ext_agent_id']}")

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
    except Exception as exc:  # noqa: BLE001 — 모델/도구 오류는 error 관측으로
        error = True
        detail = str(exc)[:500]

    return {
        "output": "".join(acc)[:_OUTPUT_CAP],
        "trace_nodes": _canonical_tokens(observed_nodes, calls_sink, broker.invocations, used_memory),
        "error": error,
        **({"detail": detail} if detail else {}),
    }
