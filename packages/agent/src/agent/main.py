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

    **모델은 항상 등록된 설정(model_cfg)에서 온다 — env는 보지 않는다.**
    model_cfg = {base_url, api_key, model_id, params}. 호출자(API)가 모델 레지스트리에서
    해석해 넘긴다. tools가 비어있으면 순수 대화.
    """
    params = params or {}
    cfg = model_cfg or {}
    base_url = cfg.get("base_url") or ""
    model_name = cfg.get("model_id") or ""
    if not base_url or not model_name:
        raise RuntimeError("모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요.")
    # 키가 없으면 무인증 로컬 엔드포인트로 간주(env 키를 빌려오지 않는다).
    api_key = cfg.get("api_key") or "sk-noauth"
    cfg_params = cfg.get("params") or {}

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
    """CLI 단독 실행(개발용 테스터) — 레지스트리가 없으므로 env에서 모델 설정을 읽어 넘긴다."""
    load_dotenv()
    model_cfg = {
        "base_url": os.environ.get("MLX_BASE_URL", "http://localhost:8045/v1"),
        "api_key": os.environ.get("MLX_API_KEY"),
        "model_id": os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8"),
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
