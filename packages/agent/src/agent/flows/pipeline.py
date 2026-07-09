"""노드형 에이전트 — 일렬 파이프라인 (스펙 259, 노코드).

사용자가 UI에서 **노드를 N개 추가**하고 노드마다 프롬프트·모델·도구를 고른다. 각 노드는 **작은
에이전트**(자기 시스템 프롬프트+자기 모델+자기 도구 부분집합)이고, 노드들은 **선언 순서대로 일렬**로
실행된다(node_0 → node_1 → … → END). 각 노드가 응답을 메시지에 append하고 다음 노드가 누적 맥락을 본다.
마지막 노드 출력이 에이전트 응답. 추적 타임라인엔 노드 이름별 실 호출이 뜬다.

**설정 주도(스펙 190 패턴)**: 로직을 박지 않고 `ctx.impl_config["nodes"]`(데이터)를 읽어 그래프를
조립한다 — 노드는 데이터(프롬프트 글자·모델 cfg·도구 이름)이고 이 엔진은 고정 신뢰 코드다. eval 없음
(085 §보안경계). **주입만 읽는다**(085 U2): 노드 모델은 플랫폼이 미리 해석해 `node["model_cfg"]`로 주입,
도구는 `ctx.tools`(이미 RBAC·브로커 스코프)에서 이름으로 필터 — 노드가 에이전트 권한을 넘을 수 없다.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from ..runtime import AgentBuildContext, AgentManifest


class _State(TypedDict):
    messages: Annotated[list, add_messages]


def _model_from_node(node: dict, ctx: AgentBuildContext) -> ChatOpenAI:
    """노드별 모델 — 플랫폼이 미리 해석해 심은 `node["model_cfg"]`를 쓰고, 없으면 에이전트 기본
    `ctx.model_cfg`로 폴백(주입 단일 출처 — env·DB 미접촉). base_url/model_id 없으면 명확히 실패."""
    cfg = node.get("model_cfg") or ctx.model_cfg or {}
    base_url = cfg.get("base_url") or ""
    model_id = cfg.get("model_id") or ""
    if not base_url or not model_id:
        raise RuntimeError("노드 모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요.")
    cfg_params = cfg.get("params") or {}
    temperature = ctx.params.get("temperature", cfg_params.get("temperature", 0.7))
    enable_thinking = cfg_params.get("enable_thinking", False)
    return ChatOpenAI(
        base_url=base_url,
        api_key=cfg.get("api_key") or "sk-noauth",
        model=model_id,
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    )


def normalize_nodes(raw: object) -> list[dict]:
    """impl_config의 노드 리스트를 방어적으로 정규화(순수 — 단위 검증 가능). dict 리스트만, prompt
    문자열 필수(빈 노드 제거), name/model/tools는 선택. 순서 보존. 잡값은 조용히 걸러 빈 리스트로."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for i, n in enumerate(raw):
        if not isinstance(n, dict):
            continue
        prompt = n.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue  # 프롬프트 없는 노드는 실행 의미 없음 — 정직하게 제외
        name = n.get("name")
        name = name.strip() if isinstance(name, str) and name.strip() else f"노드{i + 1}"
        tools = n.get("tools")
        tools = [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []
        out.append({
            "name": name,
            "prompt": prompt,
            "model_cfg": n.get("model_cfg") if isinstance(n.get("model_cfg"), dict) else None,
            "tools": tools,
        })
    return out


def _unique_node_ids(nodes: list[dict]) -> list[str]:
    """그래프 노드 id(이름 충돌 시 접미 — LangGraph 노드명 유일 요구). 표시 이름은 별개 보존."""
    seen: dict[str, int] = {}
    ids: list[str] = []
    for n in nodes:
        base = n["name"]
        if base in seen:
            seen[base] += 1
            ids.append(f"{base}#{seen[base]}")
        else:
            seen[base] = 0
            ids.append(base)
    return ids


class LinearPipelineAgent:
    """노드형(일렬 파이프라인) 커스텀 에이전트 — describe()/build_graph(ctx). NAME=`pipeline`."""

    NAME = "pipeline"

    def describe(self) -> AgentManifest:
        # 노드가 도구를 고르므로 mcps/vectorTables(도구 풀)·memories(회상)를 소비. 노드 자체 설정은
        # nodes 표면. supports_hil=True: 노드가 승인 도구를 바인딩하면 브로커/도구 HIL이 발화(정직).
        return AgentManifest(
            name="pipeline",
            consumes=("nodes", "mcps", "vectorTables", "memories"),
            description="노드를 순서대로 실행하는 파이프라인 에이전트(노코드, 스펙 259)",
            supports_hil=True,
        )

    def build_graph(self, ctx: AgentBuildContext):
        nodes = normalize_nodes((ctx.impl_config or {}).get("nodes"))
        if not nodes:
            # 노드 없음 — 조용한 빈 그래프 대신 단일 패스스루로 정직하게(입력을 그대로 모델에 태워
            # 최소 동작). 기본 모델도 없으면 build 시점에 명확히 실패(_model_from_node).
            nodes = [{"name": "노드1", "prompt": "사용자 입력에 답하세요.", "model_cfg": None, "tools": []}]

        by_name = {t.name: t for t in (ctx.tools or [])}
        ids = _unique_node_ids(nodes)
        g = StateGraph(_State)

        def _make_step(node: dict):
            model = _model_from_node(node, ctx)
            node_tools = [by_name[name] for name in node["tools"] if name in by_name]
            bound = model.bind_tools(node_tools) if node_tools else model
            prompt = node["prompt"]

            async def _step(state: _State) -> dict:
                sys = SystemMessage(content=prompt)
                resp = await bound.ainvoke([sys, *state["messages"]])
                return {"messages": [resp]}

            return _step, node_tools

        # 노드 등록 + 노드별 도구 루프(도구 있으면 <id>__tools ToolNode 자기 루프).
        steps: list[tuple] = []
        for nid, node in zip(ids, nodes):
            step, node_tools = _make_step(node)
            g.add_node(nid, step)
            steps.append((nid, node_tools))

        g.add_edge(START, ids[0])
        for i, (nid, node_tools) in enumerate(steps):
            nxt = ids[i + 1] if i + 1 < len(ids) else END
            if node_tools:
                tools_id = f"{nid}__tools"
                g.add_node(tools_id, ToolNode(node_tools))

                def _route(state: _State, _nxt=nxt, _tools_id=tools_id) -> str:
                    last = state["messages"][-1]
                    return _tools_id if getattr(last, "tool_calls", None) else _nxt

                g.add_conditional_edges(nid, _route, {tools_id: tools_id, nxt: nxt})
                g.add_edge(tools_id, nid)  # 도구 실행 후 같은 노드 재진입(표준 루프)
            else:
                g.add_edge(nid, nxt)
        return g.compile(checkpointer=ctx.checkpointer)
