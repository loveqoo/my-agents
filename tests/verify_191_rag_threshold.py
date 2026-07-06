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


# ── [F] 컬렉션별 후필터 ─────────────────────────────────────
hits = [_hit(0.9, "docs"), _hit(0.4, "docs"), _hit(0.6, "prod"), _hit(0.2, "prod"), _hit(0.5, "docs")]
r = runtime._apply_min_scores(hits, {"docs": 0.5, "prod": 0.5})
# docs≥0.5 → 0.9,0.5 / prod≥0.5 → 0.6 (0.4docs·0.2prod 드롭)
ok(len(r) == 3 and {h["score"] for h in r} == {0.9, 0.5, 0.6}, "[F1] 컬렉션별 판정(docs 0.9·0.5, prod 0.6)")
r2 = runtime._apply_min_scores(hits, {"docs": 0.5})  # prod 무설정=무필터
ok(len(r2) == 4 and any(h["score"] == 0.2 for h in r2), "[F2] 미설정 컬렉션(prod)은 무필터")
ok(len(runtime._apply_min_scores(hits, {})) == 5, "[F3] 빈 맵 = 무필터")
ok(len(runtime._apply_min_scores(hits, {"docs": 0})) == 5, "[F4] 값 0 = 무필터")
ok(len(runtime._apply_min_scores(hits, None)) == 5, "[F5] None = 무필터")
# docs≥0.5 → 0.9,0.5 통과(2) / prod≥0.7 → 없음. 컬렉션 독립 판정.
ok(len(runtime._apply_min_scores(hits, {"docs": 0.5, "prod": 0.7})) == 2, "[F6] 경계·컬렉션 독립(0.9·0.5 docs, prod 0건)")
# 방어: 비정상 값은 그 컬렉션 무필터
ok(len(runtime._apply_min_scores(hits, {"docs": 1.5, "prod": "x"})) == 5, "[F7] 비정상 값 → 무필터")


# ── [N] 맵 정규화 ───────────────────────────────────────────
ok(runtime._norm_min_scores({"a": 0.5, "b": 0, "z": 0.9}, ["a", "b"]) == {"a": 0.5}, "[N1] 컬렉션 한정 + 0/무관 제거")
ok(runtime._norm_min_scores({"a": 1.5}, ["a"]) == {}, "[N2] 범위 밖 → 제거")
ok(runtime._norm_min_scores(None) == {}, "[N3] None → 빈 맵")


# ── [D] 히트 표시 구조 ──────────────────────────────────────
detail = runtime._hits_detail([_hit(0.81234, "kb", "doc.pdf", "hello\nworld " * 40)])
ok(detail[0]["score"] == 0.812, "[D1] score 3자리 반올림")
ok(detail[0]["filename"] == "doc.pdf" and detail[0]["collection"] == "kb", "[D2] filename·collection 보존")
ok(len(detail[0]["textPreview"]) <= 241 and "\n" not in detail[0]["textPreview"], "[D3] 본문 프리뷰 캡+개행 제거")
ok(runtime._hits_detail([]) == [], "[D4] 빈 결과 → 빈 리스트")
# [D5] 비밀 마스킹 — trace 누출 방지(087/092/125, resultPreview와 동일 규율). 원문 비밀 미노출.
_masked = runtime._hits_detail([_hit(0.8, "kb", "f", "token sk-ABCDEF1234567890ABCDEF tail " * 20)])[0]["textPreview"]
ok("sk-ABCDEF1234567890ABCDEF" not in _masked and "«secret»" in _masked, "[D5] textPreview 비밀 마스킹(누출 0)")


# ── [W] 직접 도구 배선 ──────────────────────────────────────
async def _direct():
    captured = {}

    async def fake_search(collections, query, top_k=4, min_scores=None):
        captured["min_scores"] = min_scores
        return [_hit(0.8, "docs-kb", "x.md", "aaa"), _hit(0.7, "docs-kb", "y.md", "bbb")]

    orig = runtime.search_collections
    runtime.search_collections = fake_search
    try:
        sink: list[dict] = []
        tool = runtime.build_rag_tool([{"name": "docs-kb"}], sink, {"docs-kb": 0.55, "무관": 0.9})
        await tool.coroutine(query="테스트 질의", top_k=4)
    finally:
        runtime.search_collections = orig

    # 배선된 컬렉션으로 한정 정규화 → "무관" 제거
    ok(captured.get("min_scores") == {"docs-kb": 0.55}, "[W1] 코어에 min_scores(배선 한정) 전달")
    e = sink[0]
    ok(e["server"] == "rag" and e["hits"] == 2, "[W2] sink 기록(server=rag, hits=2)")
    ok(len(e["hitsDetail"]) == 2 and e["hitsDetail"][0]["collection"] == "docs-kb", "[W3] sink hitsDetail(컬렉션 포함)")
    ok(e["minScores"] == {"docs-kb": 0.55}, "[W4] sink에 minScores 맵")

    # [W5] 직접 sink의 result 필드도 비밀 마스킹(codex 적대검토 — 브로커 resultPreview와 대칭)
    async def fake_secret(collections, query, top_k=4, min_scores=None):
        return [_hit(0.8, "docs-kb", "s.md", "api key sk-DEADBEEF0123456789DEADBEEF here")]

    runtime.search_collections = fake_secret
    try:
        sink2: list[dict] = []
        tool2 = runtime.build_rag_tool([{"name": "docs-kb"}], sink2, {})
        await tool2.coroutine(query="q", top_k=4)
    finally:
        runtime.search_collections = orig
    ok("sk-DEADBEEF0123456789DEADBEEF" not in sink2[0]["result"], "[W5] 직접 sink result 비밀 마스킹(누출 0)")


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
ok("ragMinScores" in AgentConfig(ragMinScores={"a": 0.3}).model_dump(), "[S3] model_dump 왕복(직렬화 누락 없음)")
for bad in [{"a": 1.5}, {"a": -0.1}, {"a": "x"}, {"a": True}, {"": 0.5}, [1, 2]]:
    try:
        AgentConfig(ragMinScores=bad)
        ok(False, f"[S4] {bad!r} 거부")
    except Exception:
        ok(True, f"[S4] {bad!r} 거부")


print("\n" + ("✅ ALL PASS (VERIFY191_OK)" if not fails else f"❌ {len(fails)} FAILED"))
sys.exit(0 if not fails else 1)
