"""스펙 190 — 노코드 산출물형(ConfigDrivenArtifactAgent) 단위 검증.

서버 없이 그래프 계약을 직접 검증한다:
[N] normalize_artifact_fields 순수 — key 없음/문자열 candidates/label 기본/required 기본
[C] config 주도 — impl_config(artifactSpec) → ctx.config → 폼 합성 → 제출 → artifact 커밋
[E] 빈 명세 — fields 없으면 폼 없이 빈 산출물(조용한 빈 폼 금지)
[D] 이중 입력 — 폼 대기 중 텍스트 후보 병합으로 완성
실행: cd packages/api && uv run python ../../tests/verify_190_nocode_artifact.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "agent" / "src"))

import agent.runtime  # noqa: F401,E402 — 부트스트랩 순서(순환 임포트 방지)

fails: list[str] = []


def check(ok: bool, name: str) -> None:
    print(("  ok  " if ok else " FAIL ") + name)
    if not ok:
        fails.append(name)


def main() -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agent.flows.artifact import ConfigDrivenArtifactAgent, normalize_artifact_fields
    from agent.runtime import AgentBuildContext, get_agent_impl

    def _cfg(tid: str) -> dict:
        return {"configurable": {"thread_id": tid}}

    # ------------------------------------------------------------ [N] normalize 순수
    print("[N] normalize_artifact_fields 순수·방어")
    got = normalize_artifact_fields({
        "fields": [
            {"key": "region", "label": "거주지", "candidates": ["서울", "부산"]},
            {"label": "키없음"},                       # key 없음 → 버림
            {"key": "memo"},                            # label 기본=key, required 기본 True
            {"key": "code", "candidates": "abc"},       # 문자열 candidates → 무시(enum 아님)
            {"key": "opt", "required": False, "candidates": ["a", "", "b"]},  # 빈 후보 제거
        ]
    })
    check(got == [
        {"key": "region", "label": "거주지", "required": True, "candidates": ["서울", "부산"]},
        {"key": "memo", "label": "memo", "required": True},
        {"key": "code", "label": "code", "required": True},  # candidates 키 없음(문자열 무시)
        {"key": "opt", "label": "opt", "required": False, "candidates": ["a", "b"]},
    ], f"N1 정규화(키없음 버림·문자열후보 무시·빈후보 제거·기본값) (got {got})")
    check(normalize_artifact_fields(None) == [] and normalize_artifact_fields({}) == [], "N2 빈 입력 → []")

    # 레지스트리 등록 확인
    check(type(get_agent_impl("artifact_form")).__name__ == "ConfigDrivenArtifactAgent", "N3 artifact_form 등록·적합")

    # ------------------------------------------------------------ [C] config 주도 폼
    print("[C] config(artifactSpec) 주도 — 폼 합성→제출→artifact")
    SPEC = {"kind": "signup", "fields": [
        {"key": "plan", "label": "요금제", "candidates": ["무료", "프로"], "required": True},
        {"key": "email", "label": "이메일", "required": True},
    ]}
    graph = ConfigDrivenArtifactAgent().build_graph(
        AgentBuildContext(prompt="p", model_cfg=None, checkpointer=InMemorySaver(), impl_config=SPEC)
    )
    r = asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "가입할게"}]}, config=_cfg("t-c")))
    pf = r["__interrupt__"][0].value
    keys = [f["key"] for f in pf.get("fields", [])]
    check(pf.get("kind") == "form" and keys == ["plan", "email"], f"C1 spec→폼 필드 2 (got {keys})")
    check(any(f["key"] == "plan" and f.get("candidates") == ["무료", "프로"] for f in pf["fields"]), "C2 후보 필드 보존")
    # 제출 → artifact(kind=spec.kind)
    r = asyncio.run(graph.ainvoke(
        Command(resume={"type": "form", "values": {"plan": "프로", "email": "a@b.c"}}), config=_cfg("t-c")))
    art = r.get("artifact")
    check(art is not None and art["kind"] == "signup", f"C3 artifact kind=spec.kind (got {art and art.get('kind')})")
    check((art or {}).get("data") == {"plan": "프로", "email": "a@b.c"}, f"C4 데이터 정확 (got {(art or {}).get('data')})")

    # ------------------------------------------------------------ [E] 빈 명세
    print("[E] 빈/없는 명세 — 조용한 빈 폼 금지, 빈 산출물로 종료")
    g2 = ConfigDrivenArtifactAgent().build_graph(
        AgentBuildContext(prompt="p", model_cfg=None, checkpointer=InMemorySaver(), impl_config={"fields": []})
    )
    r = asyncio.run(g2.ainvoke({"messages": [{"role": "user", "content": "hi"}]}, config=_cfg("t-e")))
    check("__interrupt__" not in r and r.get("artifact", {}).get("kind") == "form-result"
          and r["artifact"]["data"] == {}, "E1 빈 명세 → interrupt 없이 빈 산출물(kind 기본)")

    # ------------------------------------------------------------ [D] 이중 입력(텍스트 병합)
    print("[D] 이중 입력 — 폼 대기 중 텍스트 후보 병합")
    g3 = ConfigDrivenArtifactAgent().build_graph(
        AgentBuildContext(prompt="p", model_cfg=None, checkpointer=InMemorySaver(),
                          impl_config={"kind": "pick", "fields": [
                              {"key": "size", "label": "크기", "candidates": ["소", "대"], "required": True}]})
    )
    asyncio.run(g3.ainvoke({"messages": [{"role": "user", "content": "고를게"}]}, config=_cfg("t-d")))
    r = asyncio.run(g3.ainvoke(Command(resume={"type": "text", "message": "대로 해줘"}), config=_cfg("t-d")))
    # confirm=False(범용은 confirm 안 씀) → 텍스트로 필수 충족 시 바로 확정
    check(r.get("artifact", {}).get("data") == {"size": "대"}, f"D1 텍스트 병합 확정 (got {r.get('artifact', {}).get('data')})")


if __name__ == "__main__":
    main()
    print("\n" + ("✅ ALL PASS (VERIFY190_OK)" if not fails else f"❌ {len(fails)} FAILED: {fails}"))
    sys.exit(1 if fails else 0)
