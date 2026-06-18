"""미니멀 하드코딩 에이전트 — 로컬 MLX + LangGraph ReAct, CLI 순수 대화.

지배 스펙: docs/spec/001-system-overview.md 의 첫 실행 증분.
실행계획: .dev/plan/001-minimal-hardcoded-agent.md
"""

import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# 하드코딩된 페르소나 (시스템 프롬프트)
PERSONA = (
    "당신은 간결하고 친절한 한국어 비서입니다. "
    "사용자의 질문에 명확하고 짧게 답하세요."
)


def build_agent():
    """환경변수에서 MLX 설정을 읽어 단일 ReAct 에이전트(툴 없음)를 만든다."""
    load_dotenv()
    base_url = os.environ.get("MLX_BASE_URL", "http://localhost:8045/v1")
    api_key = os.environ.get("MLX_API_KEY")
    model_name = os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8")

    if not api_key:
        sys.exit("MLX_API_KEY 환경변수가 필요합니다 (.env.example 참고).")

    model = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        temperature=0.7,
    )
    # 툴 없음 = 순수 대화. 페르소나는 시스템 프롬프트로 주입.
    return create_react_agent(model, tools=[], prompt=PERSONA)


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
