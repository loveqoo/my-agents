"""생성 플로우 — classify→분기 라우터 (스펙 099, `agent-flow` 스킬 데모 산출물).

**셋째 구현**. `DefaultUiAgent`(단일 ReAct)·`PlanExecuteAgent`(선형 2노드)와 달리 **조건 분기**
그래프다 — `classify`(결정적, 모델 호출 없음)가 입력을 판별해 `answer_a`/`answer_b` 중 **하나만**
발화한다. 한 실행의 추적 타임라인은 [classify, answer_a] *또는* [classify, answer_b]로, 선형
plan_execute와 구조가 달라 인터페이스가 특정 형태에 과적합되지 않았음을 노드열로 재측정한다.

구조: `classify`(질문 여부 판별 → route="a"/"b") → 조건분기 → `answer_a`(직답 모드) /
`answer_b`(부연·정리 모드). 두 분기 모두 주입된 model_cfg로 실제 모델 호출, END로 수렴.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, TypedDict

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from ..model import build_chat_openai
from ..runtime import AgentBuildContext, AgentManifest
from ..toolbox import last_user_text

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


class _State(TypedDict):
    messages: Annotated[list, add_messages]
    route: str


def classify_route(text: str) -> str:
    """결정적 분류 — 질문("?" 포함)이면 직답 분기 "a", 아니면 부연·정리 분기 "b".
    모델 호출 없음(추적 타임라인에 classify 노드가 결정적으로 1줄). 스킬 생성 로직의 자리."""
    return "a" if "?" in text else "b"


class RouteAgent:
    """classify→분기 라우터 커스텀 에이전트. 인터페이스 적합 — describe()/build_graph(ctx)."""

    def describe(self) -> AgentManifest:
        return AgentManifest(
            consumes=("memories",),  # 스펙 206 — 분기 데모: 도구·문서 미소비(persona 회상만)
            name="route",
            description="분기 라우터(classify→answer_a/answer_b) — 조건분기 예제 커스텀 에이전트",
            supports_hil=False,  # 위험 도구 게이트·interrupt 없음(순수 분기) — 정직하게 표기
        )

    def build_graph(self, ctx: AgentBuildContext) -> CompiledStateGraph:
        model = build_chat_openai(ctx.model_cfg, ctx.params)
        persona = ctx.persona  # 오버라이드 병합 후 주입된 페르소나(주입 단일 출처)

        def classify(state: _State) -> dict:
            # 결정적 — 모델 호출 없음. 노드 발화가 updates 스트림→추적 타임라인에 남는다.
            return {"route": classify_route(last_user_text(state))}

        def _pick(state: _State) -> str:
            return "answer_a" if state["route"] == "a" else "answer_b"

        async def answer_a(state: _State) -> dict:
            sys = SystemMessage(content=f"{persona}\n\n# 모드\n질문에 직접·간결하게 답하세요.")
            resp = await model.ainvoke([sys, *state["messages"]])
            return {"messages": [resp]}

        async def answer_b(state: _State) -> dict:
            sys = SystemMessage(
                content=f"{persona}\n\n# 모드\n입력을 정리하고 필요한 부연을 덧붙여 답하세요."
            )
            resp = await model.ainvoke([sys, *state["messages"]])
            return {"messages": [resp]}

        g = StateGraph(_State)
        g.add_node("classify", classify)
        g.add_node("answer_a", answer_a)
        g.add_node("answer_b", answer_b)
        g.add_edge(START, "classify")
        g.add_conditional_edges("classify", _pick, {"answer_a": "answer_a", "answer_b": "answer_b"})
        g.add_edge("answer_a", END)
        g.add_edge("answer_b", END)
        # checkpointer 주입 보존(이 그래프는 interrupt 없지만 HIL 계약 배선은 유지).
        return g.compile(checkpointer=ctx.checkpointer)
