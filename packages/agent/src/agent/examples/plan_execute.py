"""예제 커스텀 에이전트 — plan→execute 2노드 그래프 (스펙 085).

**둘째 구현**(learning 039: "drop-in은 둘째 구현을 *출하*해야 측정된다"). `DefaultUiAgent`는
`create_agent`(단일 ReAct 그래프)를 감싸지만, 이 에이전트는 **손수 만든 다노드 StateGraph**다.
둘 다 같은 플랫폼 루프로 스트림되고 둘 다 주입·추적을 받으면 인터페이스가 `create_agent`에
*과적합(누수)되지 않았음*이 측정된다.

구조: `plan`(결정적 — 모델 호출 없이 계획 힌트만 주입, 노드 발화가 추적 타임라인에 1줄) →
`execute`(주입된 model_cfg로 실제 모델 호출, 토큰 스트림). 추적 인스펙터엔 [plan, execute]가
실 호출 스택으로 뜬다(하드코딩 아님).

도구-인지(스펙 202 — 노코드 계약 "설정=동작"): 플랫폼이 주입한 `ctx.tools`(config.mcps 유래)를
소비한다 — plan은 계획에 도구 활용 단계를 반영(결정적 유지, 086 계약 보존), execute는 bind_tools로
모델이 **필요할 때만** 호출(강제 아님 — 사용자 결정), tool_calls가 있으면 `tools`(ToolNode) 노드로
실행 후 execute 재진입(표준 루프). 도구가 없으면 기존 2노드 그대로(무회귀).
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
    plan: str


def _model_from_cfg(ctx: AgentBuildContext) -> ChatOpenAI:
    """주입된 model_cfg로 ChatOpenAI 구성(build_agent와 동일 규칙 — 모델은 레지스트리 해석본만).
    env 안 봄. base_url/model_id 없으면 명확히 실패."""
    cfg = ctx.model_cfg or {}
    base_url = cfg.get("base_url") or ""
    model_id = cfg.get("model_id") or ""
    if not base_url or not model_id:
        raise RuntimeError("모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요.")
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


class PlanExecuteAgent:
    """plan→execute 커스텀 에이전트. 인터페이스 적합 — describe()/build_graph(ctx)."""

    def describe(self) -> AgentManifest:
        return AgentManifest(
            name="plan-execute",
            consumes=("mcps", "vectorTables", "memories"),  # 202부터 ctx.tools(mcp+rag)·persona(회상) 소비
            description="2노드(plan→execute) 예제 커스텀 에이전트 — 인터페이스 누수 측정용",
            supports_hil=False,  # 위험 도구 게이트 없음(순수 2노드) — 정직하게 표기
        )

    def build_graph(self, ctx: AgentBuildContext):
        model = _model_from_cfg(ctx)
        persona = ctx.persona  # 오버라이드 병합 후 주입된 페르소나(주입 단일 출처)
        # 플랫폼 주입 도구(config.mcps 유래, HIL/트레이스 래핑 포함) — 하이브리드 게이트(스펙 203):
        # 임계 이하 직접 바인딩, 초과면 검색 창구(search_tools·call_tool)로 컨텍스트 보호.
        from ..toolbox import effective_tools

        tools, discovery = effective_tools(ctx.tools)
        bound = model.bind_tools(tools) if tools else model  # 필요할 때만 호출 — 강제 아님(스펙 202)

        def plan(state: _State) -> dict:
            # 결정적 — 모델 호출 없음(스펙 086 계약: plan<execute 실측). 도구가 있으면 계획에 도구
            # 활용 단계를 반영(스펙 202) — '핵심'·'근거' 문구는 계약 보존.
            if discovery:
                return {"plan": (
                    "1) 질문의 핵심을 파악한다 2) 필요하면 도구 검색(search_tools)으로 알맞은 도구를 "
                    "찾아(call_tool) 사실을 확인한다 3) 단계적으로 근거를 들어 답한다"
                )}
            if tools:
                names = ", ".join(t.name for t in tools)
                return {"plan": (
                    f"1) 질문의 핵심을 파악한다 2) 필요하면 도구({names})로 사실을 확인한다 "
                    "3) 단계적으로 근거를 들어 답한다"
                )}
            return {"plan": "1) 질문의 핵심을 파악한다 2) 단계적으로 근거를 들어 답한다"}

        async def execute(state: _State) -> dict:
            # 주입된 모델로 실제 호출 — stream_mode="messages"가 이 토큰을 플랫폼에 흘린다.
            tool_hint = ""
            if tools:
                lines = "\n".join(
                    f"- {t.name}: {((t.description or '').strip().splitlines() or [''])[0][:120]}"
                    for t in tools
                )
                tool_hint = f"\n\n# 사용 가능한 도구 — 계획상 필요할 때만 호출\n{lines}"
            sys = SystemMessage(
                content=f"{persona}\n\n# 작업 계획\n{state['plan']}\n위 계획에 따라 답하세요.{tool_hint}"
            )
            resp = await bound.ainvoke([sys, *state["messages"]])
            return {"messages": [resp]}

        def _route(state: _State) -> str:
            # execute 응답에 tool_calls가 있으면 도구 실행 후 재진입, 없으면 종료(표준 도구 루프).
            last = state["messages"][-1]
            return "tools" if getattr(last, "tool_calls", None) else END

        g = StateGraph(_State)
        g.add_node("plan", plan)
        g.add_node("execute", execute)
        g.add_edge(START, "plan")
        g.add_edge("plan", "execute")
        if tools:
            # 도구 배선(스펙 202) — 주입 도구를 ToolNode로. 루프 상한은 langgraph recursion limit.
            g.add_node("tools", ToolNode(tools))
            g.add_conditional_edges("execute", _route, {"tools": "tools", END: END})
            g.add_edge("tools", "execute")
        else:
            g.add_edge("execute", END)  # 도구 없음 → 기존 2노드 그대로(무회귀)
        # checkpointer 주입(있으면 HIL 계약 호환 — 이 그래프는 interrupt 없지만 배선은 보존).
        return g.compile(checkpointer=ctx.checkpointer)
