"""생성 플로우 — classify→분기 라우터 (스펙 099, `agent-flow` 스킬 데모 산출물).

**셋째 구현**. `DefaultUiAgent`(단일 ReAct)·`PlanExecuteAgent`(선형 2노드)와 달리 **조건 분기**
그래프다 — `classify`(결정적, 모델 호출 없음)가 입력을 판별해 `answer_a`/`answer_b` 중 **하나만**
발화한다. 한 실행의 추적 타임라인은 [classify, answer_a] *또는* [classify, answer_b]로, 선형
plan_execute와 구조가 달라 인터페이스가 특정 형태에 과적합되지 않았음을 노드열로 재측정한다.

구조: `classify`(질문 여부 판별 → route="a"/"b") → 조건분기 → `answer_a`(직답 모드) /
`answer_b`(부연·정리 모드). 두 분기 모두 주입된 model_cfg로 실제 모델 호출, END로 수렴.
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
    route: str


def _model_from_cfg(ctx: AgentBuildContext) -> ChatOpenAI:
    """주입된 model_cfg로 ChatOpenAI 구성(plan_execute와 동일 규칙 — 모델은 레지스트리 해석본만).
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


def _last_user_text(state: _State) -> str:
    """마지막 사용자 메시지의 텍스트(분류 입력). 없으면 빈 문자열."""
    for msg in reversed(state["messages"]):
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if content:
            return content if isinstance(content, str) else str(content)
    return ""


def classify_route(text: str) -> str:
    """결정적 분류 — 질문("?" 포함)이면 직답 분기 "a", 아니면 부연·정리 분기 "b".
    모델 호출 없음(추적 타임라인에 classify 노드가 결정적으로 1줄). 스킬 생성 로직의 자리."""
    return "a" if "?" in text else "b"


class RouteAgent:
    """classify→분기 라우터 커스텀 에이전트. 인터페이스 적합 — describe()/build_graph(ctx)."""

    def describe(self) -> AgentManifest:
        return AgentManifest(
            name="route",
            description="분기 라우터(classify→answer_a/answer_b) — 조건분기 예제 커스텀 에이전트",
            supports_hil=False,  # 위험 도구 게이트·interrupt 없음(순수 분기) — 정직하게 표기
        )

    def build_graph(self, ctx: AgentBuildContext):
        model = _model_from_cfg(ctx)
        persona = ctx.persona  # 오버라이드 병합 후 주입된 페르소나(주입 단일 출처)

        def classify(state: _State) -> dict:
            # 결정적 — 모델 호출 없음. 노드 발화가 updates 스트림→추적 타임라인에 남는다.
            return {"route": classify_route(_last_user_text(state))}

        def _pick(state: _State) -> str:
            return "answer_a" if state["route"] == "a" else "answer_b"

        async def answer_a(state: _State) -> dict:
            sys = SystemMessage(
                content=f"{persona}\n\n# 모드\n질문에 직접·간결하게 답하세요."
            )
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
