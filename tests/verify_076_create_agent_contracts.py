"""스펙 076 검증 — create_react_agent → langchain.agents.create_agent 마이그레이션.

verify_041이 interrupt/resume/checkpointer 배선(astream 멀티모드 + Command(resume))을 덮으므로,
여기선 나머지 두 호출계약을 스모크로 덮는다(LLM 불요 — 스크립트 스텁 모델):
  C1. `.invoke({"messages": [...]})` → messages 키 반환(main.py:93 경로).
  C2. `.astream(..., stream_mode="messages")` → 토큰 청크 스트림(chat.py:485 경로).
  C3. import·빌드 시 create_react_agent DeprecationWarning 부재(전환 완료 증거).

실행: uv run python tests/verify_076_create_agent_contracts.py
"""

import asyncio
import sys
import warnings

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


def _build_with_stub(monkeypatch_model):
    """build_agent를 태우되 ChatOpenAI 대신 스텁 모델을 주입(엔드포인트 불요)."""
    import agent.main as m

    orig = m.ChatOpenAI
    m.ChatOpenAI = lambda **kw: monkeypatch_model  # noqa: E731
    try:
        return m.build_agent(
            persona="너는 간결한 비서다.",
            model_cfg={"base_url": "http://x", "model_id": "stub", "params": {}},
        )
    finally:
        m.ChatOpenAI = orig


def main() -> int:
    fails = []

    # C3: 마이그레이션 후 deprecation 경고가 없어야 함(빌드 경로에서 포착).
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        stub = GenericFakeChatModel(messages=iter([AIMessage(content="안녕하세요, 무엇을 도와드릴까요?")]))
        graph = _build_with_stub(stub)
    deprecations = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "create_react_agent" in str(w.message)
    ]
    if deprecations:
        fails.append(f"C3 create_react_agent DeprecationWarning 잔존: {[str(w.message) for w in deprecations]}")
    else:
        print("C3 PASS — create_react_agent DeprecationWarning 없음(전환 완료)")

    # C1: .invoke({"messages"}) → messages 키.
    result = graph.invoke({"messages": [{"role": "user", "content": "안녕"}]})
    if not (isinstance(result, dict) and "messages" in result and result["messages"]):
        fails.append(f"C1 invoke messages 키 없음: keys={list(result) if isinstance(result, dict) else type(result)}")
    else:
        last = result["messages"][-1]
        print(f"C1 PASS — invoke messages 반환, 최종='{getattr(last, 'content', last)[:30]}'")

    # C2: .astream(stream_mode="messages") → 토큰 청크.
    async def _stream():
        stub2 = GenericFakeChatModel(messages=iter([AIMessage(content="네 도와드릴게요")]))
        g2 = _build_with_stub(stub2)
        chunks = []
        async for chunk in g2.astream(
            {"messages": [{"role": "user", "content": "도와줘"}]}, stream_mode="messages"
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_stream())
    if not chunks:
        fails.append("C2 astream(stream_mode='messages') 청크 0개")
    else:
        print(f"C2 PASS — astream messages 청크 {len(chunks)}개(스트리밍 계약 보존)")

    if fails:
        print("\nFAIL:")
        for f in fails:
            print(" -", f)
        return 1
    print("\nALL PASS — create_agent 호출계약 보존(C1 invoke, C2 astream messages, C3 no-deprecation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
