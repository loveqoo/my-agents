"""미니멀 하드코딩 에이전트 — OpenAI 호환 모델 + LangGraph ReAct, CLI 순수 대화.

지배 스펙: docs/spec/001-system-overview.md 의 첫 실행 증분.
실행계획: .dev/plan/001-minimal-hardcoded-agent.md
모델은 특정 벤더에 묶지 않는다 — CLI 단독 실행은 일반 `MODEL_*` env로 임의 OpenAI 호환
엔드포인트를 가리킨다(스펙 059, MLX는 더 이상 특별 취급 안 함).
"""

import os
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from .model import build_chat_openai

# 기본 프롬프트 (CLI 등 호출자가 지정하지 않을 때)
PROMPT = "당신은 간결하고 친절한 한국어 비서입니다. 사용자의 질문에 명확하고 짧게 답하세요."


def build_agent(
    prompt: str = PROMPT,
    params: dict | None = None,
    tools: list | None = None,
    model_cfg: dict | None = None,
    checkpointer: Any = None,
) -> CompiledStateGraph:
    """prompt/params/tools로 단일 ReAct 에이전트를 만든다.

    **모델은 항상 등록된 설정(model_cfg)에서 온다 — env는 보지 않는다.**
    model_cfg = {base_url, api_key, model_id, params}. 호출자(API)가 모델 레지스트리에서
    해석해 넘긴다. tools가 비어있으면 순수 대화.

    checkpointer: HIL 승인 게이팅(스펙 041)용 durable 체크포인터. 주면 그래프가 상태를 박아
    도구 내부 interrupt()로 일시정지·재개할 수 있다. None이면 기존 무상태 동작(무회귀).
    """
    # 모델은 항상 등록 설정(model_cfg)에서 — env 미조회, 키 없으면 무인증 로컬. 정본=model.build_chat_openai.
    model = build_chat_openai(model_cfg, params)
    # 하이브리드 도구 접근(스펙 203) — 임계 이하 직접 바인딩(코드 경로 동일=무회귀), 초과면 검색
    # 창구(search_tools·call_tool)로 컨텍스트 보호. discovery 모드면 사용 안내 1줄을 프롬프트에 부가.
    from .toolbox import DISCOVERY_HINT, effective_tools

    eff_tools, discovery = effective_tools(tools)
    system_prompt = f"{prompt}\n\n# 도구 안내\n{DISCOVERY_HINT}" if discovery else prompt
    # create_agent = 구 create_react_agent 후속(스펙 076). prompt 파라미터는 prompt→system_prompt.
    # 정적 문자열 prompt만 쓰므로 1:1 대응(콜러블 prompt 제거 영향 없음). 반환물은 동일한 컴파일
    # LangGraph 그래프 → invoke/astream/ainvoke(Command)/__interrupt__ 계약 보존(verify_041로 증명).
    return create_agent(
        model=model, tools=eff_tools, system_prompt=system_prompt, checkpointer=checkpointer
    )


def main() -> None:
    """CLI 단독 실행(개발용 테스터) — 레지스트리가 없으므로 env에서 모델 설정을 읽어 넘긴다.

    벤더 무관 `MODEL_*` env로 임의 OpenAI 호환 엔드포인트를 가리킨다(스펙 059). 기본 base_url은
    이 API의 mock 엔드포인트라 무외부에서도 동작한다(API가 떠 있을 때). 실 모델을 쓰려면
    MODEL_BASE_URL/MODEL_API_KEY/MODEL_ID로 가리킨다.
    """
    load_dotenv()
    model_cfg = {
        "base_url": os.environ.get("MODEL_BASE_URL", "http://127.0.0.1:8000/_remote/v1"),
        "api_key": os.environ.get("MODEL_API_KEY", "sk-noauth"),
        "model_id": os.environ.get("MODEL_ID", "mock-chat"),
        "params": {},
    }
    agent = build_agent(model_cfg=model_cfg)
    print("하드코딩 에이전트 (종료: 'exit' 또는 Ctrl-D)")
    messages = []  # 대화 맥락 유지 (멀티턴)
    while True:
        try:
            user = input("\n사용자> ").strip()
        except EOFError:
            print()
            break
        if user in {"exit", "quit"}:
            break
        if not user:
            continue
        messages.append({"role": "user", "content": user})
        result = agent.invoke({"messages": messages})
        messages = result["messages"]  # AI 응답까지 포함한 전체 히스토리로 갱신
        print(f"\n에이전트> {messages[-1].content}")


if __name__ == "__main__":
    main()
