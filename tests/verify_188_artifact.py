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
    )
    from agent.runtime import AgentBuildContext

    class _SlotDemo(ArtifactAgentBase):
        """뼈대 검증용 테스트 전용 데모(스펙 327 — 프로덕션 SlotFillDemoAgent 제거 후 여기로 이전).
        고정 3필드를 ask 루프로 채운다(빈 답은 같은 필드 3회까지 되물음 → '(미입력)')."""

        NAME = "artifact_test_slot"
        FIELDS = (("destination", "목적지"), ("period", "기간"), ("budget", "예산"))

        async def produce(self, ctx: ProduceContext) -> Artifact:
            values: dict = {}
            for key, label in self.FIELDS:
                for _ in range(3):
                    ans = ctx.ask(f"{label}을(를) 알려주세요")
                    if ans:
                        values[key] = ans
                        break
                else:
                    values[key] = "(미입력)"
            return Artifact(kind="travel-request", data=values, raw=ctx.text)

    print("[A] ask 멀티턴 — slot-fill 완주(테스트 전용 데모)")

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

    result, questions = _run(_SlotDemo(), "t-slotfill", ["서울", "3월 2일부터 3일", "50만원"])
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
        _SlotDemo(), "t-retry", ["", "서울", "3월", "", "", "", ]
    )
    # 첫 답 빈 값 → 목적지 재질문(질문 4회 이상), 예산은 3회 빈 답 → "(미입력)"
    check(questions.count(questions[0].split(" (")[0]) >= 1 and len(questions) >= 5, "B1 재질문 발생")
    art = result.get("artifact")
    check(art is not None and art["data"]["destination"] == "서울", "B2 재질문 후 값 채움")
    check(art is not None and art["data"]["budget"] == "(미입력)", "B3 3회 빈 답 → (미입력)")

    print("[F] 폼 순수함수")
    from agent.flows.artifact import (
        merge_text_into_fields,
        missing_required,
        validate_form_values,
    )

    FIELDS = [
        {"key": "gender", "label": "성별", "candidates": ["남성", "여성"], "required": True},
        {"key": "memo", "label": "메모", "required": False},
        {"key": "city", "label": "도시", "candidates": ["서울", "부산"], "required": True},
    ]
    v = validate_form_values(FIELDS, {"gender": "남성", "city": "화성", "unknown": "x", "memo": ""})
    check(v == {"gender": "남성"}, "F1 검증: 후보밖·미지키·빈값 제거")
    check(missing_required(FIELDS, {"gender": "남성"}) == ["city"], "F2 필수 미충족 목록")
    m = merge_text_into_fields(FIELDS, {"gender": "여성"}, "서울 사는 남성")
    check(m == {"gender": "여성", "city": "서울"}, "F3 텍스트 병합: 빈 필드만·기존값 보존")
    # (F4·F5는 스펙 327에서 폐기 — entity_ids_from_rag_text·match_entities가 targeting 데모와 함께 제거됨)
    # P2-1: candidates가 리스트가 아니면(문자열 등) enum 게이트를 하지 않는다 — 안 그러면
    # `"xyz" in "abc..."` substring 오판정으로 후보 밖 값이 통과/탈락한다(적대 검증 하드닝).
    vbad = validate_form_values([{"key": "code", "candidates": "abc"}], {"code": "xyz"})
    check(vbad == {"code": "xyz"}, "F6 문자열 candidates는 enum 게이트 무시(substring 오판정 제거)")

    print("[FM] ctx.form 이중 입력 — 제출·텍스트 병합·재제시")

    class FormDemoAgent(ArtifactAgentBase):
        NAME = "artifact_test_form"

        async def produce(self, ctx: ProduceContext) -> Artifact:
            vals = await ctx.form(
                [
                    {"key": "gender", "label": "성별", "candidates": ["남성", "여성"], "required": True},
                    {"key": "city", "label": "도시", "candidates": ["서울", "부산"], "required": True},
                ]
            )
            return Artifact(kind="form-demo", data=vals)

    graph = FormDemoAgent().build_graph(
        AgentBuildContext(persona="p", model_cfg=None, checkpointer=InMemorySaver())
    )
    r = asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "시작"}]}, config=_cfg("t-form")))
    p0 = r["__interrupt__"][0].value
    check(p0.get("kind") == "form" and len(p0["fields"]) == 2, "FM1 form interrupt(필드 2)")
    # 제출: 후보 밖 값(city=화성)은 뼈대 재검증서 탈락 → 재제시(note 포함)
    r = asyncio.run(graph.ainvoke(
        Command(resume={"type": "form", "values": {"gender": "남성", "city": "화성"}}), config=_cfg("t-form")))
    p1 = r["__interrupt__"][0].value
    check(p1.get("kind") == "form" and p1["prefill"] == {"gender": "남성"} and "note" in p1,
          "FM2 후보밖 값 탈락→갱신 프리필로 재제시+note")
    # 이중 입력: 폼 대기 중 텍스트 → 후보 매칭 병합 → 전부 참 → 완료
    r = asyncio.run(graph.ainvoke(Command(resume={"type": "text", "message": "부산이야"}), config=_cfg("t-form")))
    check(r.get("artifact", {}).get("data") == {"gender": "남성", "city": "부산"},
          "FM3 텍스트 병합으로 완성(이중 입력, confirm=False → 직접 확정)")

    print("[FC] confirm=True — 텍스트 병합 후 무확인 확정 안 함(적대 검증 P2-2)")

    class ConfirmFormAgent(ArtifactAgentBase):
        NAME = "artifact_test_confirm"

        async def produce(self, ctx: ProduceContext) -> Artifact:
            vals = await ctx.form(
                [{"key": "city", "label": "도시", "candidates": ["서울", "부산"], "required": True}],
                confirm=True,
            )
            return Artifact(kind="cf", data=vals)

    g2 = ConfirmFormAgent().build_graph(
        AgentBuildContext(persona="p", model_cfg=None, checkpointer=InMemorySaver())
    )
    r = asyncio.run(g2.ainvoke({"messages": [{"role": "user", "content": "부산 살아"}]}, config=_cfg("t-cf")))
    check(r["__interrupt__"][0].value.get("kind") == "form", "FC1 confirm 폼 제시")
    # 텍스트로 부산을 채워 필수가 전부 차더라도 confirm이면 **재제시**(무확인 확정 봉인).
    r = asyncio.run(g2.ainvoke(Command(resume={"type": "text", "message": "부산으로 해줘"}), config=_cfg("t-cf")))
    check("__interrupt__" in r and "artifact" not in r, "FC2 텍스트 병합 후 재제시(무확인 확정 안 함)")
    check(r["__interrupt__"][0].value.get("prefill") == {"city": "부산"}, "FC3 재제시 프리필=병합값")
    # 폼 제출(명시 확정)로만 최종 확정.
    r = asyncio.run(g2.ainvoke(Command(resume={"type": "form", "values": {"city": "부산"}}), config=_cfg("t-cf")))
    check(r.get("artifact", {}).get("data") == {"city": "부산"}, "FC4 폼 제출로 확정")

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
