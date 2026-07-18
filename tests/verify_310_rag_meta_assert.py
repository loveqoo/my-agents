"""스펙 310 검증 — rag_meta_contains 판정 + 러너 meta 노출.

Part A(단위, 합성 obs): 부분일치·조합 AND·키 부재·숫자/문자 관대·미지정 키 무시·malformed→ValueError
  ·**fail-closed**(rag 관측 부재=agent 런)·meta=None(문서형 hit).
Part B(통합, movies-demo 실검색): eval_run_rag obs가 hit meta를 실어 내리는지 + 정답 엔티티 통과·오답 실패.

실행(Part B는 dev 서버 8000 + movies-demo 필요): cd packages/api && uv run python ../../tests/verify_310_rag_meta_assert.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api.eval_harness import build_asserts  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _fn(arg: str):
    """build_asserts로 닫힌 집합 등록까지 태워 scorer fn 하나를 얻는다."""
    return build_asserts([{"type": "rag_meta_contains", "arg": arg}])[0][1]


def _obs(*metas) -> dict:
    return {
        "rag": {
            "hits": [
                {"score": 0.9, "filename": "movies.jsonl", "text": "..", "meta": m} for m in metas
            ]
        }
    }


# 두 엔티티 hit(인터스텔라 101 / 라라랜드 110)
OBS = _obs(
    {"movie_id": 101, "director_id": 1, "genre_id": 1},
    {"movie_id": 110, "director_id": 9, "genre_id": 6},
)


def part_a() -> None:
    print("── Part A: 단위(합성 obs) ──")
    check(_fn("movie_id=101")(OBS), "부분일치: 존재 엔티티 → 통과")
    check(not _fn("movie_id=999")(OBS), "존재하지 않는 id → 실패")
    check(_fn("director_id=9,genre_id=6")(OBS), "조합 AND: 라라랜드(9,6) → 통과")
    check(
        not _fn("director_id=9,genre_id=1")(OBS),
        "조합 AND: 한 hit이 둘 다 만족해야(9는 110·1은 101 분산) → 실패",
    )
    check(_fn("movie_id=101")(OBS), "숫자 meta(101)와 문자 arg('101') 관대 비교 → 통과")
    check(_fn("movie_id=101")(OBS), "미지정 키(director/genre) 무시 → 통과")
    check(not _fn("foo=1")(OBS), "meta에 없는 키 → 불일치")
    # fail-closed: rag 관측 부재(agent 런)
    check(
        not _fn("movie_id=101")({"trace_nodes": ["rag:x"], "output": ".."}),
        "rag 관측 부재(agent 런) → False(fail-closed)",
    )
    check(not _fn("movie_id=101")({"rag": {"hits": []}}), "빈 hits → False")
    # meta=None 문서형 hit
    check(not _fn("movie_id=101")(_obs(None)), "meta=None(문서형 hit) → 불일치")
    # codex 회귀: str(None)=="None" 누출 봉인 — 부재 키/None을 "None" arg가 통과시키면 안 됨
    check(not _fn("foo=None")(OBS), "codex: 부재 키 vs arg 'None' → 불일치(str(None) 누출 봉인)")
    check(not _fn("foo=None")(_obs(None)), "codex: meta=None hit vs 'None' → 불일치")
    check(
        not _fn("label_cate_id=None")(_obs({"label_cate_id": None, "movie_id": 5})),
        "codex: null id(label_cate_id) vs 'None' → 불일치",
    )
    # codex 회귀: 비스칼라 repr 매칭 봉인(bool·dict·list는 엔티티 id 아님)
    check(not _fn("flag=True")(_obs({"flag": True})), "codex: bool meta repr 매칭 → 불일치")
    check(not _fn("cfg={'a': 1}")(_obs({"cfg": {"a": 1}})), "codex: dict meta repr 매칭 → 불일치")
    check(not _fn("tags=['a']")(_obs({"tags": ["a"]})), "codex: list meta repr 매칭 → 불일치")
    # malformed arg → ValueError(→ API 400)
    for bad in ("movie_id", "=5", "k=", "movie_id=101,bad"):
        try:
            _fn(bad)
            check(False, f"malformed arg {bad!r} → ValueError 기대(안 남)")
        except ValueError:
            check(True, f"malformed arg {bad!r} → ValueError(400)")


async def part_b() -> int:
    print("\n── Part B: 통합(movies-demo 실검색) ──")
    import json

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from api import crypto
    from api.db import SessionLocal
    from api.eval_runner import eval_run_rag
    from api.models import Collection, ModelConfig

    async with SessionLocal() as s:
        c = (
            await s.execute(
                select(Collection)
                .where(Collection.name == "movies-demo")
                .options(
                    selectinload(Collection.embedding_model).selectinload(ModelConfig.provider)
                )
            )
        ).scalar_one_or_none()
        if c is None:
            print("  ..  movies-demo 없음 — 스킬로 먼저 적재 필요(Part B 스킵)")
            return 0
        em = c.embedding_model
        ep = em.provider
        col = {
            "id": c.id,
            "name": c.name,
            "embed_base_url": ep.base_url,
            "embed_api_key": crypto.decrypt(ep.api_key),
            "embed_model_id": em.model_id,
        }

    # 첫 영화 data로 질의(mock=결정적) — 반환된 상위 엔티티를 실측해 그 movie_id로 판정.
    with open(
        os.path.join(ROOT, "packages", "api", "data", "entity_samples", "movies.jsonl"), "rb"
    ) as f:
        first = json.loads(f.read().splitlines()[0])
    obs = await eval_run_rag(col, first["data"])
    hits = obs.get("rag", {}).get("hits", [])
    check(bool(hits), f"eval_run_rag 검색 결과 {len(hits)}건")
    top_meta = hits[0].get("meta") if hits else None
    check(
        isinstance(top_meta, dict) and top_meta.get("movie_id") is not None,
        f"러너 obs가 hit meta 실림: {top_meta}",
    )
    if isinstance(top_meta, dict):
        mid = top_meta["movie_id"]
        check(_fn(f"movie_id={mid}")(obs), f"정답 엔티티(movie_id={mid}) → 통과")
        check(not _fn("movie_id=99999")(obs), "결과에 없는 movie_id → 실패")
    return 0


async def main() -> None:
    part_a()
    await part_b()
    print()
    if _fails:
        print(f"FAIL: {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("VERIFY310_OK — rag_meta_contains 부분일치·fail-closed + 러너 meta 노출")


if __name__ == "__main__":
    asyncio.run(main())
