"""스펙 188 P1 — 산출물형 에이전트 뼈대(ArtifactAgentBase) 단위 검증.

서버 없이 그래프 계약을 직접 검증한다:
[U] 순수함수 — _first_json_obj·_resume_text·summarize_artifact
[A] ask 멀티턴 — interrupt(kind=ask) → Command(resume) 반복 → 최종 artifact 커밋
[R] 리플레이 캐시 — 재개마다 produce가 재실행돼도 tool/rag는 정확히 1회(스텝 캐시)
[B] 되물음 — 빈 답이면 같은 필드 재질문(상한 3회 후 "(미입력)")
[G] 구조 검증 — produce가 Artifact 아닌 걸 반환하면 명시적 실패
실행: cd packages/api && uv run python ../../tests/verify_188_artifact.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "agent" / "src"))

import agent.runtime  # noqa: F401,E402 — 부트스트랩 순서: runtime 먼저(순환 임포트 방지, flows 공통)

fails: list[str] = []


def check(ok: bool, name: str) -> None:
    print(("  ok  " if ok else " FAIL ") + name)
    if not ok:
        fails.append(name)


# ================================================================ [U] 순수함수
def unit_checks() -> None:
    from agent.flows.artifact import Artifact, _first_json_obj, _resume_text, summarize_artifact

    print("[U] 순수함수")
    check(_first_json_obj('앞말 {"a": 1, "b": "x"} 뒷말') == {"a": 1, "b": "x"}, "U1 JSON 추출")
    check(_first_json_obj("json 없음") == {}, "U2 JSON 없음 → {}")
    check(_first_json_obj('{"broken": } {"ok": true}') == {"ok": True}, "U3 파싱 실패 후 다음 후보")
    check(_resume_text({"type": "text", "message": "서울"}) == "서울", "U4 union 봉투(text)")
    check(_resume_text("날문자열") == "날문자열", "U5 레거시 문자열 수용")
    s = summarize_artifact(Artifact(kind="travel-request", data={"목적지": "서울", "예산": "50만원"}))
    check("travel-request" in s and "목적지=서울" in s, "U6 요약 문자열")


# ================================================================ [A/R/B/G] 그래프 계약
def graph_checks() -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agent.flows.artifact import (
        Artifact,
        ArtifactAgentBase,
        ProduceContext,
        SlotFillDemoAgent,
    )
    from agent.runtime import AgentBuildContext

    print("[A] ask 멀티턴 — slot-fill 데모 완주")

    def _cfg(tid: str) -> dict:
        return {"configurable": {"thread_id": tid}}

    def _run(agent, tid: str, answers: list[str]) -> tuple[dict, list[str]]:
        """user 첫 발화 후, interrupt마다 answers를 순서대로 재개. (최종 state values, 질문들) 반환."""
        graph = agent.build_graph(
            AgentBuildContext(persona="p", model_cfg=None, checkpointer=InMemorySaver())
        )
        questions: list[str] = []
        result = asyncio.run(
            graph.ainvoke({"messages": [{"role": "user", "content": "출장 신청할게"}]}, config=_cfg(tid))
        )
        i = 0
        while "__interrupt__" in result and i < len(answers):
            payload = result["__interrupt__"][0].value
            questions.append(payload.get("text", ""))
            check(payload.get("kind") == "ask", f"A-kind interrupt kind=ask ({i})")
            result = asyncio.run(
                graph.ainvoke(
                    Command(resume={"type": "text", "message": answers[i]}), config=_cfg(tid)
                )
            )
            i += 1
        return result, questions

    result, questions = _run(SlotFillDemoAgent(), "t-slotfill", ["서울", "3월 2일부터 3일", "50만원"])
    art = result.get("artifact")
    check(art is not None and art["kind"] == "travel-request", "A1 artifact 커밋(kind)")
    check(
        art is not None
        and art["data"] == {"destination": "서울", "period": "3월 2일부터 3일", "budget": "50만원"},
        "A2 3필드 값 정확",
    )
    check(len(questions) == 3 and "목적지" in questions[0], "A3 질문 3회·첫 질문=목적지")
    msgs = result.get("messages") or []
    last = msgs[-1] if msgs else None
    check(last is not None and "산출물 완성" in str(getattr(last, "content", "")), "A4 최종 요약 메시지")

    print("[R] 리플레이 캐시 — tool은 재개들에도 정확히 1회")

    class CountingBroker:
        def __init__(self):
            self.calls = 0

        async def invoke(self, cap_id, args):
            self.calls += 1
            return {"cap": cap_id, "n": self.calls}

    class ToolThenAskAgent(ArtifactAgentBase):
        NAME = "artifact_test_tool"

        async def produce(self, ctx: ProduceContext) -> Artifact:
            ent = await ctx.tool("mcp:demo/get_entity", {"id": "x"})  # ask 이전 — 재개마다 재실행 위험
            a1 = ctx.ask("q1?")
            a2 = ctx.ask("q2?")
            return Artifact(kind="t", data={"ent_n": ent["n"], "a1": a1, "a2": a2})

    broker = CountingBroker()
    agent = ToolThenAskAgent()
    graph = agent.build_graph(
        AgentBuildContext(persona="p", model_cfg=None, checkpointer=InMemorySaver(), broker=broker)
    )
    r = asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "go"}]}, config=_cfg("t-replay")))
    r = asyncio.run(graph.ainvoke(Command(resume={"type": "text", "message": "답1"}), config=_cfg("t-replay")))
    r = asyncio.run(graph.ainvoke(Command(resume={"type": "text", "message": "답2"}), config=_cfg("t-replay")))
    check(r.get("artifact", {}).get("data", {}).get("a2") == "답2", "R1 완주(두 ask 답 반영)")
    check(broker.calls == 1, f"R2 tool 호출 정확히 1회 (실제 {broker.calls}회 — 리플레이 캐시)")
    check(r.get("artifact", {}).get("data", {}).get("ent_n") == 1, "R3 리플레이가 기록된 결과 반환")

    print("[B] 되물음 — 빈 답 재질문·상한")
    result, questions = _run(
        SlotFillDemoAgent(), "t-retry", ["", "서울", "3월", "", "", "", ]
    )
    # 첫 답 빈 값 → 목적지 재질문(질문 4회 이상), 예산은 3회 빈 답 → "(미입력)"
    check(questions.count(questions[0].split(" (")[0]) >= 1 and len(questions) >= 5, "B1 재질문 발생")
    art = result.get("artifact")
    check(art is not None and art["data"]["destination"] == "서울", "B2 재질문 후 값 채움")
    check(art is not None and art["data"]["budget"] == "(미입력)", "B3 3회 빈 답 → (미입력)")

    print("[G] 구조 검증 — 잘못된 produce 반환은 명시적 실패")

    class BadAgent(ArtifactAgentBase):
        NAME = "artifact_test_bad"

        async def produce(self, ctx: ProduceContext):
            return {"not": "an artifact"}

    bad_graph = BadAgent().build_graph(
        AgentBuildContext(persona="p", model_cfg=None, checkpointer=InMemorySaver())
    )
    try:
        asyncio.run(bad_graph.ainvoke({"messages": [{"role": "user", "content": "x"}]}, config=_cfg("t-bad")))
        check(False, "G1 Artifact 아닌 반환 → RuntimeError")
    except RuntimeError:
        check(True, "G1 Artifact 아닌 반환 → RuntimeError")


unit_checks()
graph_checks()

if fails:
    print(f"\n❌ FAIL — {len(fails)}건")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("\n✅ ALL PASS (VERIFY188_OK)")
