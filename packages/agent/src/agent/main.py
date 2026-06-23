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


def build_agent(
    persona: str = PERSONA,
    params: dict | None = None,
    tools: list | None = None,
    model_cfg: dict | None = None,
):
    """persona/params/tools로 단일 ReAct 에이전트를 만든다.

    model_cfg가 주어지면 등록된 모델 설정(base_url/api_key/model_id/params)으로 LLM을 띄우고,
    없으면 env의 로컬 MLX로 폴백한다. tools가 비어있으면 순수 대화.
    """
    load_dotenv()
    params = params or {}

    # 모델 설정은 원자적으로 다룬다: 등록 모델이 해석되면 그 필드만 쓰고,
    # 없을 때만 env MLX로 폴백한다. (등록 base_url에 env api_key가 섞여 다른
    # 엔드포인트로 키가 새는 것을 방지 — codex P1)
    if model_cfg:
        base_url = model_cfg.get("base_url") or ""
        model_name = model_cfg.get("model_id") or ""
        if not base_url or not model_name:
            raise RuntimeError("등록된 모델 설정이 불완전합니다 (base_url/model_id 필요).")
        # 등록 모델에 키가 없으면 무인증 로컬 엔드포인트로 간주 — env 키를 빌려오지 않는다.
        api_key = model_cfg.get("api_key") or "sk-noauth"
        cfg_params = model_cfg.get("params") or {}
    else:
        base_url = os.environ.get("MLX_BASE_URL", "http://localhost:8045/v1")
        api_key = os.environ.get("MLX_API_KEY")
        model_name = os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8")
        cfg_params = {}
        if not api_key:
            raise RuntimeError("API 키가 필요합니다 (모델 등록 또는 MLX_API_KEY).")

    # temperature: 호출자 params > 모델 등록 params > 기본
    temperature = params.get("temperature", cfg_params.get("temperature", 0.7))
    # thinking 비활성(Qwen): 모델 params로 끌 수 있게, 기본은 비활성
    enable_thinking = cfg_params.get("enable_thinking", False)

    model = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    )
    return create_react_agent(model, tools=tools or [], prompt=persona)


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
