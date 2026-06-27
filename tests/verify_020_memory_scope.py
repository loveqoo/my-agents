"""스펙 020 검증 — mem0 다층 스코프 + 카탈로그 리맵 (인프라 불요, 순수 로직).

라이브 mem0/Postgres 없이 새로 도입된 핵심 로직을 격리 검증한다:
  1. search() 다축 병합·dedup·정렬·top-k
  2. user↔session 격리(부분집합 필터로도 남의 기억이 새지 않음)
  3. add() 제공 축 전부 태깅 / 빈 스코프는 무저장
  4. 마이그레이션 _remap_memories 의 옛→새 이름 치환(중복 제거·순서 보존)

라이브 mem0 필터 AND 의미·실제 회상은 사용자 브랜치 통합 테스트에서 확인(스펙 020 검증 절).
실행: .venv/bin/python tests/verify_020_memory_scope.py
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import memory as M  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class FakeMem:
    """필터의 단일 축으로 store를 거른다(mem0 단축 검색을 모사). add는 kwargs를 기록."""

    def __init__(self, store: list[dict]):
        self.store = store
        self.added: list[tuple] = []

    def search(self, query, filters, top_k):  # mem0 2.0.7 시그니처(top_k=)
        (axis, val), = filters.items()
        rows = [r for r in self.store if r.get(axis) == val]
        return {"results": rows[:top_k]}

    def add(self, messages, **kwargs):
        self.added.append((messages, kwargs))


def with_mem(mem):
    """resolve_backend를 FakeMem 주입 Mem0Backend로 패치(실제 백엔드 병합 경로를 탄다)."""
    from api.memory.mem0_backend import Mem0Backend
    backend = Mem0Backend.__new__(Mem0Backend)
    backend._mem = mem
    M.resolve_backend = lambda mem_cfg: backend  # type: ignore[assignment]


# ---------------------------------------------------------------- search 병합/격리
def test_search() -> None:
    print("[search] 다축 병합·dedup·격리")
    store = [
        # alice 의 유저 기억(세션 가로지름) — user_id 만 태깅된 옛 기억
        {"id": "u1", "memory": "alice는 비건이다", "score": 0.9, "user_id": "alice"},
        # alice 의 풍부 태깅 기억 — user_id + run_id 둘 다 (양쪽 검색에 잡혀야 하나 1번만)
        {"id": "ur1", "memory": "alice는 s1에서 파이썬을 물었다", "score": 0.8, "user_id": "alice", "run_id": "s1"},
        # 익명 세션 s2 기억 — run_id 만
        {"id": "r2", "memory": "s2 세션의 사실", "score": 0.7, "run_id": "s2"},
        # bob 의 유저 기억
        {"id": "b1", "memory": "bob은 매운 걸 싫어한다", "score": 0.95, "user_id": "bob"},
    ]
    with_mem(FakeMem(store))

    # alice + s1: user 기억 ∪ 세션 기억, ur1 은 dedup 으로 1회만, 남(bob/s2)은 안 보여야.
    hits = M.search({"user_id": "alice", "run_id": "s1"}, "q", {"x": 1}, limit=10)
    ids = [h["text"] for h in hits]
    check(any("비건" in t for t in ids), "alice 유저 기억 회상")
    check(any("파이썬" in t for t in ids), "alice+s1 공유 기억 회상")
    check(sum(1 for h in hits if "파이썬" in h["text"]) == 1, "풍부 태깅 기억 dedup(1회)")
    check(not any("bob" in t for t in ids), "bob 유저 기억 누출 없음")
    check(not any("s2" in t for t in ids), "타 세션(s2) 누출 없음")

    # 정렬: score 내림차순
    scores = [h["score"] for h in hits]
    check(scores == sorted(scores, reverse=True), "score 내림차순 정렬")

    # scope 축 표기: 비건은 user_id 로 회상
    vegan = next(h for h in hits if "비건" in h["text"])
    check(vegan["scope"] == "user_id", "유저 기억 scope=user_id 표기")

    # 익명(userId 없음): run_id 만 → s2 기억만, 유저 기억 안 보임
    hits2 = M.search({"user_id": None, "run_id": "s2"}, "q", {"x": 1}, limit=10)
    t2 = [h["text"] for h in hits2]
    check(any("s2" in t for t in t2) and not any("alice" in t or "bob" in t for t in t2),
          "익명 세션은 run_id 기억만(유저 기억 격리)")

    # top-k 절단: limit 적용
    hits3 = M.search({"user_id": "alice", "run_id": "s1"}, "q", {"x": 1}, limit=1)
    check(len(hits3) == 1, "top-k limit 절단")

    # dedup 시 더 높은 score 유지
    store2 = [
        {"id": "x", "memory": "동일 기억", "score": 0.4, "user_id": "alice"},
        {"id": "x", "memory": "동일 기억", "score": 0.85, "run_id": "s1"},
    ]
    with_mem(FakeMem(store2))
    h = M.search({"user_id": "alice", "run_id": "s1"}, "q", {"x": 1}, limit=10)
    check(len(h) == 1 and h[0]["score"] == 0.85, "dedup 시 높은 score 유지")


# ---------------------------------------------------------------- add 다축 태깅
def test_add() -> None:
    print("[add] 다축 태깅 / 빈 스코프 무저장")
    m = FakeMem([])
    with_mem(m)
    msgs = [{"role": "user", "content": "hi"}]

    # add는 infer=도 함께 넘긴다(스펙 029) → 스코프 축만 추려 비교.
    def axes(kw):
        return {k: v for k, v in kw.items() if k != "infer"}

    M.add({"user_id": "alice", "run_id": "s1"}, msgs, {"x": 1})
    check(m.added and axes(m.added[-1][1]) == {"user_id": "alice", "run_id": "s1"},
          "userId 있으면 user_id+run_id 동시 태깅")

    M.add({"user_id": None, "run_id": "s1"}, msgs, {"x": 1})
    check(axes(m.added[-1][1]) == {"run_id": "s1"}, "userId 없으면 run_id 만 태깅")

    before = len(m.added)
    M.add({"user_id": None, "run_id": None}, msgs, {"x": 1})
    check(len(m.added) == before, "빈 스코프는 저장 안 함")

    # agent_id 는 이번 스펙에서 None 고정 — 들어오면 태깅되긴 하나 chat.py 가 안 넘김.
    M.add({"user_id": "alice", "run_id": "s1", "agent_id": None}, msgs, {"x": 1})
    check("agent_id" not in m.added[-1][1], "agent_id=None 은 태깅에서 제외")


# ---------------------------------------------------------------- 마이그레이션 리맵
def test_migration_remap() -> None:
    print("[migration] config.memories 옛→새 리맵(dedup·순서)")
    path = os.path.join(ROOT, "packages", "api", "alembic", "versions",
                        "c1d2e3f4a5b6_realign_memory_catalog.py")
    spec = importlib.util.spec_from_file_location("mig020", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    class FakeResult:
        def __init__(self, rows): self._rows = rows
        def fetchall(self): return self._rows

    class FakeConn:
        def __init__(self, rows_by_table):
            self.rows = rows_by_table
            self.updates: list[tuple] = []
        def execute(self, stmt, params=None):
            sql = str(stmt)
            if sql.strip().upper().startswith("SELECT"):
                table = "agent_versions" if "agent_versions" in sql else "agents"
                return FakeResult(list(self.rows.get(table, [])))
            if sql.strip().upper().startswith("UPDATE"):
                self.updates.append((sql, params))
            return None

    conn = FakeConn({
        "agents": [
            ("a1", {"memories": ["단기(세션)", "장기·일화적", "절차적"], "historyDepth": 40}),
            ("a2", {"memories": ["단기(세션)", "장기·의미론적"]}),
            ("a3", {"memories": ["단기(세션)"]}),  # 변경 없음 → UPDATE 안 나야
        ],
        "agent_versions": [],
    })
    mig._remap_memories(conn, mig._RENAME)

    updated = {p["id"]: p for _sql, p in conn.updates}
    import json
    check("a1" in updated, "a1(일화/절차) 업데이트됨")
    if "a1" in updated:
        mems = json.loads(updated["a1"]["c"])["memories"]
        check(mems == ["단기(세션)", "장기 기억 (mem0)"],
              "일화+절차 → 장기 기억(mem0)로 흡수·중복 제거·순서 보존")
        check("historyDepth" in json.loads(updated["a1"]["c"]),
              "config 의 다른 키 보존")
    check("a2" in updated and json.loads(updated["a2"]["c"])["memories"] == ["단기(세션)", "장기 기억 (mem0)"],
          "의미론적 → 장기 기억(mem0)")
    check("a3" not in updated, "변경 없는 행은 UPDATE 안 함")


if __name__ == "__main__":
    test_search()
    test_add()
    test_migration_remap()
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")
