"""verify_194 — 채점 기준 lte(이하) scorer + assertLabel 대칭 (스펙 194 P2·C).

  build_asserts가 rag_hits_lte·rag_score_lte를 만들고 채점(경계·fail-closed·범위 거부). gte 무회귀.
실행: uv run --project packages/api python tests/verify_194_assert_lte.py
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

from api.eval_harness import build_asserts  # noqa: E402

_fails: list[str] = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def only(spec):
    return build_asserts([spec])[0][1]


# rag_hits_lte
f = only({"type": "rag_hits_lte", "arg": "2"})
check(f({"rag": {"hits": [1, 2]}}) is True, "hits_lte 경계(2<=2) 통과")
check(f({"rag": {"hits": [1, 2, 3]}}) is False, "hits_lte 초과(3<=2) 실패")
check(f({"rag": {"hits": []}}) is True, "hits_lte 0건 통과(0<=2)")
check(
    f({}) is False, "hits_lte rag 관측 부재(agent 런) → False(fail-closed — 빈 관측 0<=N 위장 차단)"
)
check(f({"rag": {}}) is False, "hits_lte rag={} → False(fail-closed)")

# rag_score_lte
g = only({"type": "rag_score_lte", "arg": "0.5"})
check(g({"rag": {"top_score": 0.3}}) is True, "score_lte 0.3<=0.5 통과")
check(g({"rag": {"top_score": 0.8}}) is False, "score_lte 0.8<=0.5 실패")
check(g({"rag": {"top_score": None}}) is False, "score_lte top_score None → False(fail-closed)")
check(g({}) is False, "score_lte 부재 → False(fail-closed)")

# 범위·형식 거부(스펙 140 fail-closed 유지)
for bad in ("1.5", "-0.1", "nan", "x"):
    try:
        build_asserts([{"type": "rag_score_lte", "arg": bad}])
        check(False, f"score_lte 잘못된 arg {bad!r} 거부해야")
    except ValueError:
        check(True, f"score_lte 잘못된 arg {bad!r} → 400(ValueError)")
try:
    build_asserts([{"type": "rag_hits_lte", "arg": "x"}])
    check(False, "hits_lte 비정수 거부해야")
except ValueError:
    check(True, "hits_lte 비정수 → 400(ValueError)")

# gte 무회귀
gg = only({"type": "rag_hits_gte", "arg": "2"})
check(
    gg({"rag": {"hits": [1, 2]}}) is True and gg({"rag": {"hits": [1]}}) is False,
    "gte 무회귀(2>=2 통과·1>=2 실패)",
)

print(
    f"\n{'✅ ALL PASS (VERIFY194_OK)' if not _fails else f'❌ {len(_fails)} FAILED'} — {passed} passed"
)
sys.exit(0 if not _fails else 1)
