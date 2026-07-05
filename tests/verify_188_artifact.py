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

    print("[F] 폼 순수함수")
    from agent.flows.artifact import (
        entity_ids_from_rag_text,
        match_entities,
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
    check(entity_ids_from_rag_text("... [entity:age_band] x [entity:gender] [entity:age_band]") == ["age_band", "gender"], "F4 rag 마커 추출(순서·중복제거)")
    cat = [{"id": "a", "label": "나이", "synonyms": ["30대"]}, {"id": "g", "label": "성별", "synonyms": ["남성"]}]
    check([e["id"] for e in match_entities("30대 남성", cat)] == ["a", "g"], "F5 엔티티 동의어 매칭")
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

    print("[T] targeting 데모 — 동적 폼 합성(가짜 브로커)")
    import json as _json
    from types import SimpleNamespace

    from agent.flows.artifact import TargetingDemoAgent

    CATALOG = {"entities": [
        {"id": "purchase_history", "label": "구매이력", "synonyms": ["구매 이력", "구매"]},
        {"id": "age_band", "label": "나이", "synonyms": ["30대", "20대"]},
        {"id": "region", "label": "거주지(시)", "synonyms": ["서울", "거주"]},
        {"id": "gender", "label": "성별", "synonyms": ["남성", "여성"]},
    ]}
    DETAILS = {
        "purchase_history": {"label": "구매이력", "candidates": ["최근", "7일 전", "최근 한 달"]},
        "age_band": {"label": "나이", "candidates": ["20대", "30대", "40대"]},
        "region": {"label": "거주지(시)", "candidates": ["서울", "부산"]},
        "gender": {"label": "성별", "candidates": ["남성", "여성"]},
    }

    class CatalogBroker:
        def __init__(self):
            self.rag_calls = 0

        async def invoke(self, cap_id, args):
            if cap_id.startswith("rag:"):
                self.rag_calls += 1
                # rag 경로도 검증: 히트 텍스트에 entity 마커(실 임베딩 환경 시뮬레이션)
                return SimpleNamespace(text="문서: 성별 항목 [entity:gender]", error=None)
            if cap_id.endswith("list_entities"):
                return SimpleNamespace(text=_json.dumps(CATALOG, ensure_ascii=False), error=None)
            if cap_id.endswith("get_entity"):
                return SimpleNamespace(
                    text=_json.dumps(DETAILS[args["entity_id"]], ensure_ascii=False), error=None)
            return SimpleNamespace(text="", error="unknown")

    tb = CatalogBroker()
    tgraph = TargetingDemoAgent().build_graph(
        AgentBuildContext(persona="p", model_cfg=None, checkpointer=InMemorySaver(), broker=tb)
    )
    # 발화에 성별 없음 — rag 마커([entity:gender])가 합류시켜 4필드가 떠야(합집합 검증)
    r = asyncio.run(tgraph.ainvoke(
        {"messages": [{"role": "user", "content": "최근 구매 이력이 있는 30대 서울 거주"}]},
        config=_cfg("t-tgt")))
    pf = r["__interrupt__"][0].value
    keys = [f["key"] for f in pf.get("fields", [])]
    check(pf.get("kind") == "form" and set(keys) == {"purchase_history", "age_band", "region", "gender"},
          f"T1 rag∪동의어 매칭 4필드 (got {keys})")
    check(pf["prefill"] == {"purchase_history": "최근", "age_band": "30대", "region": "서울"},
          f"T2 발화 프리필 3건(성별 제외) (got {pf['prefill']})")
    # 폼 대기 중 텍스트로 성별 보완(이중 입력). confirm=True라 필수가 전부 차더라도 곧장 확정하지
    # 않고 **갱신 프리필(4건)로 재제시**한다(무확인 확정 봉인 — 적대 검증 P2-2).
    r = asyncio.run(tgraph.ainvoke(Command(resume={"type": "text", "message": "성별은 남성이야"}), config=_cfg("t-tgt")))
    check("__interrupt__" in r and "artifact" not in r, "T3a 텍스트 보완 후 재제시(무확인 확정 안 함)")
    pf2 = r["__interrupt__"][0].value
    check(pf2.get("prefill") == {"purchase_history": "최근", "age_band": "30대", "region": "서울", "gender": "남성"},
          f"T3b 재제시 프리필 4건(성별 병합 반영) (got {pf2.get('prefill')})")
    # 폼 제출(명시 확정)로 산출물 완성.
    r = asyncio.run(tgraph.ainvoke(
        Command(resume={"type": "form", "values": pf2["prefill"]}), config=_cfg("t-tgt")))
    art = r.get("artifact")
    check(art is not None and art["kind"] == "targeting", "T3 targeting artifact 완성")
    conds = {c["entity_id"]: c["value"] for c in (art or {}).get("data", {}).get("conditions", [])}
    check(conds == {"purchase_history": "최근", "age_band": "30대", "region": "서울", "gender": "남성"},
          f"T4 conditions 값 4건 정확 (got {conds})")

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
