"""스펙 191 v2 단위 — 컬렉션별 RAG 최소 유사도 필터 + 구조화 trace(히트 카드·검색어).

[F] _apply_min_scores: 컬렉션별 판정·경계 포함·빈맵=무필터·미설정 컬렉션 무필터.
[N] _norm_min_scores: 컬렉션 한정 + 0/무효 제거.
[D] _hits_detail: 컬렉션·파일명·유사도(반올림)·본문 프리뷰(캡).
[W] build_rag_tool: 코어에 min_scores 맵 전달 + sink에 hitsDetail/minScores(직접 경로).
[B] RagProvider: row.name으로 임계값 조회 + invoke raw에 hitsDetail/minScore(scalar)/query(브로커).
[S] 스키마: ragMinScores 맵 검증(각 값 0~1, bool/문자열/키/범위 거부) + 왕복(model_dump).

실행: uv run --project packages/api python tests/verify_191_rag_threshold.py
"""

import asyncio
import sys

from api import runtime
from api.schemas import AgentConfig

fails: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        fails.append(msg)


def _hit(score, coll="a", name="a.md", text="t"):
    return {"score": score, "collection": coll, "filename": name, "text": text, "meta": None}


# ── [F] 컬렉션별 커트라인 표시(annotate) + used 분리 (스펙 192) ────────
# _annotate_cutoffs는 드롭하지 않고 belowCutoff/cutoff를 부착 / used_hits가 통과분만 거른다.
def _used(hits, ms):
    return runtime.used_hits(runtime._annotate_cutoffs(hits, ms))


hits = [
    _hit(0.9, "docs"),
    _hit(0.4, "docs"),
    _hit(0.6, "prod"),
    _hit(0.2, "prod"),
    _hit(0.5, "docs"),
]
u = _used(hits, {"docs": 0.5, "prod": 0.5})
# docs≥0.5 → 0.9,0.5 / prod≥0.5 → 0.6 (0.4docs·0.2prod 미달)
ok(
    len(u) == 3 and {h["score"] for h in u} == {0.9, 0.5, 0.6},
    "[F1] used=통과분(docs 0.9·0.5, prod 0.6)",
)
ok(
    len(_used(hits, {"docs": 0.5})) == 4
    and any(h["score"] == 0.2 for h in _used(hits, {"docs": 0.5})),
    "[F2] 미설정 컬렉션(prod)은 무필터",
)
ok(len(_used(hits, {})) == 5, "[F3] 빈 맵 = 무필터")
ok(len(_used(hits, {"docs": 0})) == 5, "[F4] 값 0 = 무필터")
ok(len(_used(hits, None)) == 5, "[F5] None = 무필터")
ok(
    len(_used(hits, {"docs": 0.5, "prod": 0.7})) == 2,
    "[F6] 경계·컬렉션 독립(0.9·0.5 docs, prod 0건)",
)
ok(len(_used(hits, {"docs": 1.5, "prod": "x"})) == 5, "[F7] 비정상 값 → 무필터")
# [F8] annotate는 **드롭 안 함** — 전부 유지 + belowCutoff 플래그(인스펙터 "못 쓴 문서"용).
ann = runtime._annotate_cutoffs(hits, {"docs": 0.5, "prod": 0.5})
dropped = [h for h in ann if h.get("belowCutoff")]
ok(
    len(ann) == 5 and len(dropped) == 2 and {h["score"] for h in dropped} == {0.4, 0.2},
    "[F8] annotate 전부 유지 + 미달 2건 belowCutoff 표시(못 쓴 문서)",
)
ok(all(h.get("cutoff") == 0.5 for h in ann if "cutoff" in h), "[F9] cutoff 값 부착")
ok(
    all("belowCutoff" not in h for h in runtime._annotate_cutoffs(hits, {})),
    "[F10] 커트라인 없으면 키 없음(외부 안전)",
)


# ── [N] 맵 정규화 ───────────────────────────────────────────
ok(
    runtime._norm_min_scores({"a": 0.5, "b": 0, "z": 0.9}, ["a", "b"]) == {"a": 0.5},
    "[N1] 컬렉션 한정 + 0/무관 제거",
)
ok(runtime._norm_min_scores({"a": 1.5}, ["a"]) == {}, "[N2] 범위 밖 → 제거")
ok(runtime._norm_min_scores(None) == {}, "[N3] None → 빈 맵")


# ── [D] 히트 표시 구조 ──────────────────────────────────────
detail = runtime._hits_detail([_hit(0.81234, "kb", "doc.pdf", "hello\nworld " * 40)])
ok(detail[0]["score"] == 0.812, "[D1] score 3자리 반올림")
ok(
    detail[0]["filename"] == "doc.pdf" and detail[0]["collection"] == "kb",
    "[D2] filename·collection 보존",
)
ok(
    len(detail[0]["textPreview"]) <= 241,
    "[D3] 본문 프리뷰 캡(개행은 스펙 255서 보존으로 변경 — 엔티티 구조화 렌더에 라인 경계 필요)",
)
ok(runtime._hits_detail([]) == [], "[D4] 빈 결과 → 빈 리스트")
# [D5] 비밀 마스킹 — trace 누출 방지(087/092/125, resultPreview와 동일 규율). 원문 비밀 미노출.
_masked = runtime._hits_detail(
    [_hit(0.8, "kb", "f", "token sk-ABCDEF1234567890ABCDEF tail " * 20)]
)[0]["textPreview"]
ok(
    "sk-ABCDEF1234567890ABCDEF" not in _masked and "«secret»" in _masked,
    "[D5] textPreview 비밀 마스킹(누출 0)",
)
# [D6] 커트라인 플래그 전달(스펙 192) — annotate된 히트의 belowCutoff/cutoff가 detail에 실림.
_ann = runtime._annotate_cutoffs([_hit(0.4, "kb"), _hit(0.8, "kb")], {"kb": 0.5})
_d6 = runtime._hits_detail(_ann)
ok(
    _d6[0]["belowCutoff"] is True and _d6[1]["belowCutoff"] is False and _d6[0]["cutoff"] == 0.5,
    "[D6] hitsDetail에 belowCutoff/cutoff 전달(못 쓴 문서 표시)",
)


# ── [W] 직접 도구 배선 ──────────────────────────────────────
async def _direct():
    captured = {}

    async def fake_search(collections, query, top_k=4, min_scores=None):
        captured["min_scores"] = min_scores
        return [_hit(0.8, "docs-kb", "x.md", "aaa"), _hit(0.7, "docs-kb", "y.md", "bbb")]

    from api import rag_runtime as RR  # 정의 모듈 패치(파사드 재수출 패치는 내부 호출에 안 먹음)

    orig = RR.search_collections
    RR.search_collections = fake_search
    try:
        sink: list[dict] = []
        tool = runtime.build_rag_tool([{"name": "docs-kb"}], sink, {"docs-kb": 0.55, "무관": 0.9})
        await tool.coroutine(query="테스트 질의", top_k=4)
    finally:
        RR.search_collections = orig

    # 배선된 컬렉션으로 한정 정규화 → "무관" 제거
    ok(captured.get("min_scores") == {"docs-kb": 0.55}, "[W1] 코어에 min_scores(배선 한정) 전달")
    e = sink[0]
    ok(e["server"] == "rag" and e["hits"] == 2, "[W2] sink 기록(server=rag, hits=2)")
    ok(
        len(e["hitsDetail"]) == 2 and e["hitsDetail"][0]["collection"] == "docs-kb",
        "[W3] sink hitsDetail(컬렉션 포함)",
    )
    ok(e["minScores"] == {"docs-kb": 0.55}, "[W4] sink에 minScores 맵")

    # [W5] 직접 sink의 result 필드도 비밀 마스킹(codex 적대검토 — 브로커 resultPreview와 대칭)
    async def fake_secret(collections, query, top_k=4, min_scores=None):
        return [_hit(0.8, "docs-kb", "s.md", "api key sk-DEADBEEF0123456789DEADBEEF here")]

    RR.search_collections = fake_secret
    try:
        sink2: list[dict] = []
        tool2 = runtime.build_rag_tool([{"name": "docs-kb"}], sink2, {})
        await tool2.coroutine(query="q", top_k=4)
    finally:
        RR.search_collections = orig
    ok(
        "sk-DEADBEEF0123456789DEADBEEF" not in sink2[0]["result"],
        "[W5] 직접 sink result 비밀 마스킹(누출 0)",
    )

    # [W6] 스펙 192 — 에이전트 결과는 used(통과분)만, hitsDetail엔 dropped(미달)도 실림.
    async def fake_annotated(collections, query, top_k=4, min_scores=None):
        # search_collections가 annotate한 것처럼 belowCutoff 부착 상태로 반환.
        return runtime._annotate_cutoffs(
            [
                _hit(0.8, "docs-kb", "keep.md", "kept"),
                _hit(0.3, "docs-kb", "drop.md", "dropped body"),
            ],
            {"docs-kb": 0.5},
        )

    RR.search_collections = fake_annotated
    try:
        sink3: list[dict] = []
        tool3 = runtime.build_rag_tool([{"name": "docs-kb"}], sink3, {"docs-kb": 0.5})
        agent_text = await tool3.coroutine(query="q", top_k=4)
    finally:
        RR.search_collections = orig
    ok(
        "keep.md" in agent_text and "drop.md" not in agent_text,
        "[W6] 에이전트 결과는 used(통과)만 — 미달 문서 안 보임",
    )
    hd = sink3[0]["hitsDetail"]
    ok(
        len(hd) == 2 and any(x.get("belowCutoff") for x in hd),
        "[W6b] hitsDetail엔 dropped(미달)도 포함(인스펙터용)",
    )
    ok(sink3[0]["hits"] == 1, "[W6c] hits 카운트=used(통과분) 수")


asyncio.run(_direct())


# ── [B] 브로커 provider ─────────────────────────────────────
async def _broker():
    from api import broker

    rp = broker.RagProvider(None, {"kb": 0.6, "other": 0.3})
    ok(rp._min_scores == {"kb": 0.6, "other": 0.3}, "[B1] RagProvider 맵 보존")

    captured = {}

    async def fake_search(collections, query, top_k=4, min_scores=None):
        captured["min_scores"] = min_scores
        return [_hit(0.9, "kb", "d.md", "body text")]

    class _Row:
        name = "kb"
        col = {"name": "kb"}

    # 브로커 RagProvider는 파사드 속성(runtime.search_collections)을 호출 시점에 읽는다 —
    # 이 경로는 파사드 패치가 정답(W 섹션의 build_rag_tool 내부 호출과 패치 지점이 다름).
    orig = runtime.search_collections
    runtime.search_collections = fake_search
    try:
        res = await rp.invoke(_Row(), {"text": "무엇을 검색?", "top_k": 4})
    finally:
        runtime.search_collections = orig

    ok(captured.get("min_scores") == {"kb": 0.6}, "[B4] 코어에 이 컬렉션 임계값 전달({kb:0.6})")
    raw = res.raw
    ok(raw.get("hits") == 1 and len(raw.get("hitsDetail", [])) == 1, "[B5] raw에 hits/hitsDetail")
    ok(raw.get("minScore") == 0.6, "[B6] raw에 minScore(이 컬렉션 scalar)")
    ok(raw.get("query") == "무엇을 검색?", "[B7] raw에 검색어(query)")


asyncio.run(_broker())


# ── [S] 스키마 왕복 ─────────────────────────────────────────
ok(AgentConfig().ragMinScores == {}, "[S1] 기본 빈 맵")
ok(AgentConfig(ragMinScores={"docs-kb": 0.5}).ragMinScores == {"docs-kb": 0.5}, "[S2] 유효 맵")
ok(
    "ragMinScores" in AgentConfig(ragMinScores={"a": 0.3}).model_dump(),
    "[S3] model_dump 왕복(직렬화 누락 없음)",
)
for bad in [{"a": 1.5}, {"a": -0.1}, {"a": "x"}, {"a": True}, {"": 0.5}, [1, 2]]:
    try:
        AgentConfig(ragMinScores=bad)
        ok(False, f"[S4] {bad!r} 거부")
    except Exception:
        ok(True, f"[S4] {bad!r} 거부")


print("\n" + ("✅ ALL PASS (VERIFY191_OK)" if not fails else f"❌ {len(fails)} FAILED"))
sys.exit(0 if not fails else 1)
