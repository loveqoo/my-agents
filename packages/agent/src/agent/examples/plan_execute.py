"""예제 커스텀 에이전트 — plan→execute 2노드 그래프 (스펙 085).

**둘째 구현**(learning 039: "drop-in은 둘째 구현을 *출하*해야 측정된다"). `DefaultUiAgent`는
`create_agent`(단일 ReAct 그래프)를 감싸지만, 이 에이전트는 **손수 만든 다노드 StateGraph**다.
둘 다 같은 플랫폼 루프로 스트림되고 둘 다 주입·추적을 받으면 인터페이스가 `create_agent`에
*과적합(누수)되지 않았음*이 측정된다.

구조: `plan`(결정적 — 모델 호출 없이 계획 힌트만 주입, 노드 발화가 추적 타임라인에 1줄) →
`execute`(주입된 model_cfg로 실제 모델 호출, 토큰 스트림). 추적 인스펙터엔 [plan, execute]가
실 호출 스택으로 뜬다(하드코딩 아님).
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

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
            description="2노드(plan→execute) 예제 커스텀 에이전트 — 인터페이스 누수 측정용",
            supports_hil=False,  # 위험 도구 게이트 없음(순수 2노드) — 정직하게 표기
        )

    def build_graph(self, ctx: AgentBuildContext):
        model = _model_from_cfg(ctx)
        persona = ctx.persona  # 오버라이드 병합 후 주입된 페르소나(주입 단일 출처)

        def plan(state: _State) -> dict:
            # 결정적 — 모델 호출 없음. 노드가 발화한 사실이 updates 스트림→추적 타임라인에 남는다.
            # (주입된 persona/params를 읽어 계획을 조형할 수도 있으나 예제는 고정 힌트로 단순화.)
            return {"plan": "1) 질문의 핵심을 파악한다 2) 단계적으로 근거를 들어 답한다"}

        async def execute(state: _State) -> dict:
            # 주입된 모델로 실제 호출 — stream_mode="messages"가 이 토큰을 플랫폼에 흘린다.
            sys = SystemMessage(
                content=f"{persona}\n\n# 작업 계획\n{state['plan']}\n위 계획에 따라 답하세요."
            )
            resp = await model.ainvoke([sys, *state["messages"]])
            return {"messages": [resp]}

        g = StateGraph(_State)
        g.add_node("plan", plan)
        g.add_node("execute", execute)
        g.add_edge(START, "plan")
        g.add_edge("plan", "execute")
        g.add_edge("execute", END)
        # checkpointer 주입(있으면 HIL 계약 호환 — 이 그래프는 interrupt 없지만 배선은 보존).
        return g.compile(checkpointer=ctx.checkpointer)
