"""미니멀 하드코딩 에이전트 — 로컬 MLX + LangGraph ReAct, CLI 순수 대화.

지배 스펙: docs/spec/001-system-overview.md 의 첫 실행 증분.
실행계획: .dev/plan/001-minimal-hardcoded-agent.md
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# 기본 페르소나 (CLI 등 호출자가 지정하지 않을 때)
PERSONA = (
    "당신은 간결하고 친절한 한국어 비서입니다. "
    "사용자의 질문에 명확하고 짧게 답하세요."
)


def build_agent(persona: str = PERSONA, params: dict | None = None):
    """persona/params로 단일 ReAct 에이전트(툴 없음)를 만든다. 모델은 env의 MLX."""
    load_dotenv()
    base_url = os.environ.get("MLX_BASE_URL", "http://localhost:8045/v1")
    api_key = os.environ.get("MLX_API_KEY")
    model_name = os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8")

    if not api_key:
        raise RuntimeError("MLX_API_KEY 환경변수가 필요합니다 (.env.example 참고).")

    params = params or {}
    model = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        temperature=params.get("temperature", 0.7),
        # Qwen thinking 비활성: 추론 토큰 폭증/콘텐츠 누락 방지 (plan 001 리스크 대응)
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    # 툴 없음 = 순수 대화. 페르소나는 시스템 프롬프트로 주입.
    return create_react_agent(model, tools=[], prompt=persona)


def main():
    agent = build_agent()
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
