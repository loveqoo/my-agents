"""스펙 040 검증 — 메모리 백엔드 추상화 계약 (인프라 불요, 순수 로직).

**drop-in 실측 증명**: `MemoryBackend` 계약을 두 독립 구현에 *동일 단언*으로 돌린다.
  - `InMemoryBackend` — mem0 코드 한 줄도 안 쓰는 dict 백엔드(완전 독립).
  - `Mem0Backend` — mem0-shape 응답을 내는 `Mem0Sim`을 주입(어댑터의 병합·정규화 경로를 탄다).
둘 다 같은 계약을 통과 = 추상화가 진짜 백엔드-중립(주장이 아니라 측정).

계약(스코프 단위, Protocol 공개 op로만 seed): 합집합 회상 / 격리 / id dedup / scope 태깅 / top-k /
빈 질의·스코프 → [] / 빈 스코프 add 무저장 / update·delete 왕복 / 없는 id → False.
또 facade graceful(backend None → 안전 기본값)과 env 기반 백엔드 선택(drop-in 기전)을 점검한다.

라이브 mem0 라운드트립은 verify_039(실 add/delete/list) + 브라우저 CRUD에서 확인(스펙 040 §5).
실행: .venv/bin/python tests/verify_040_memory_backend_contract.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api.memory.inmemory_backend import InMemoryBackend  # noqa: E402
from api.memory.mem0_backend import Mem0Backend  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Mem0Sim:
    """mem0 2.0.7 관측 표면을 모사 — 축 태깅 저장 + 단일 축 필터 + mem0-shape 응답(results/id/memory/score).

    Mem0Backend 어댑터의 축별 병합·응답 정규화(res["results"], r["memory"])를 실제로 태우기 위한 스텁.
    """

    def __init__(self):
        self.recs: list[dict] = []  # {id, memory, axes:{...}}
        self._seq = 0

    def add(self, messages, infer=True, **axes):
        for m in messages:
            text = (m.get("content") or "").strip()
            if not text:
                continue
            self._seq += 1
            self.recs.append({"id": f"m0-{self._seq}", "memory": text, "axes": dict(axes)})

    def _match(self, rec, filters):
        (axis, val), = filters.items()
        return rec["axes"].get(axis) == val

    def search(self, query, filters, top_k):
        out = []
        for r in self.recs:
            if self._match(r, filters) and query.lower() in r["memory"].lower():
                score = round(min(1.0, len(query) / max(1, len(r["memory"]))), 3)
                out.append({"id": r["id"], "memory": r["memory"], "score": score})
        return {"results": out[:top_k]}

    def get_all(self, filters):
        return {"results": [{"id": r["id"], "memory": r["memory"]} for r in self.recs if self._match(r, filters)]}

    def update(self, memory_id, data):
        for r in self.recs:
            if r["id"] == memory_id:
                r["memory"] = data
                return
        raise KeyError(memory_id)

    def delete(self, memory_id):
        before = len(self.recs)
        self.recs = [r for r in self.recs if r["id"] != memory_id]
        if len(self.recs) == before:
            raise KeyError(memory_id)


def make_inmemory():
    return InMemoryBackend()


def make_mem0():
    b = Mem0Backend.__new__(Mem0Backend)  # __init__는 mem0 임포트 → 우회하고 Sim 주입
    b._mem = Mem0Sim()
    return b


# ---------------------------------------------------------------- 공유 계약
def run_contract(name: str, make_backend) -> None:
    print(f"[contract:{name}]")
    b = make_backend()
    # F1 user_id=alice / F2 run_id=s1 / F3 alice+s1(양축) / F4 user_id=bob
    b.add({"user_id": "alice"}, [{"role": "user", "content": "alice는 비건이다"}], True)
    b.add({"run_id": "s1"}, [{"role": "user", "content": "세션 사실 파이썬"}], True)
    b.add({"user_id": "alice", "run_id": "s1"}, [{"role": "user", "content": "공유 사실 파이썬 비건"}], True)
    b.add({"user_id": "bob"}, [{"role": "user", "content": "bob의 매운맛 사실"}], True)

    # list_all: 합집합(F1,F2,F3) + 격리(bob 없음) + dedup(F3 1회)
    rows = b.list_all({"user_id": "alice", "run_id": "s1"})
    ids = [r["id"] for r in rows]
    texts = {r["text"] for r in rows}
    check(len(ids) == len(set(ids)), f"{name}: list_all id dedup(양축 기억 1회)")
    check(len(rows) == 3, f"{name}: list_all 합집합(F1+F2+F3=3)")
    check(not any("bob" in t for t in texts), f"{name}: list_all 격리(bob 누출 없음)")
    check(b.list_all({}) == [], f"{name}: 빈 스코프 list_all → []")

    # search: 합집합 회상 + scope 태깅 + dedup + 격리 + 정렬
    hits = b.search({"user_id": "alice", "run_id": "s1"}, "파이썬", 10)
    ht = [h["text"] for h in hits]
    check(any("세션 사실" in t for t in ht), f"{name}: run_id 기억 회상(F2)")
    check(any("공유 사실" in t for t in ht), f"{name}: 양축 기억 회상(F3)")
    check(sum(1 for t in ht if "공유 사실" in t) == 1, f"{name}: 양축 기억 dedup(1회)")
    check(all(h["scope"] in ("user_id", "run_id", "agent_id") for h in hits), f"{name}: hit scope 축 태깅")
    check(all(set(h) == {"type", "text", "score", "scope"} for h in hits), f"{name}: hit shape")
    check(not any("매운맛" in t for t in ht), f"{name}: search 격리(bob 없음)")
    scores = [h["score"] for h in hits]
    check(scores == sorted(scores, reverse=True), f"{name}: score 내림차순 정렬")

    # top-k 절단 / 빈 질의·스코프
    check(len(b.search({"user_id": "alice", "run_id": "s1"}, "파이썬", 1)) == 1, f"{name}: top-k 절단")
    check(b.search({"user_id": "alice"}, "", 10) == [], f"{name}: 빈 질의 → []")
    check(b.search({}, "q", 10) == [], f"{name}: 빈 스코프 search → []")

    # 빈 스코프 add 무저장
    b.add({}, [{"role": "user", "content": "orphan 파이썬"}], True)
    check(not any("orphan" in h["text"] for h in b.search({"user_id": "alice", "run_id": "s1"}, "orphan", 10)),
          f"{name}: 빈 스코프 add 무저장")

    # update 왕복(id 지정)
    target = next(r for r in b.list_all({"user_id": "alice"}) if "비건이다" in r["text"])
    check(b.update(target["id"], "수정된 사실") is True, f"{name}: update True")
    after = {r["id"]: r["text"] for r in b.list_all({"user_id": "alice"})}
    check(after.get(target["id"]) == "수정된 사실", f"{name}: update 본문 반영")

    # delete 왕복
    check(b.delete(target["id"]) is True, f"{name}: delete True")
    check(target["id"] not in {r["id"] for r in b.list_all({"user_id": "alice"})}, f"{name}: delete 반영")

    # 없는 id → False
    check(b.update("nope", "x") is False, f"{name}: 없는 id update False")
    check(b.delete("nope") is False, f"{name}: 없는 id delete False")


# ---------------------------------------------------------------- facade graceful + drop-in 선택
def test_facade_graceful() -> None:
    print("[facade] backend None → 안전 기본값")
    from api import memory as M
    check(M.search({"user_id": "a"}, "q", None) == [], "search(None cfg) → []")
    check(M.list_memories({"user_id": "a"}, None) == [], "list_memories(None cfg) → []")
    check(M.update_memory("x", "y", None) is False, "update_memory(None cfg) → False")
    check(M.delete_memory("x", None) is False, "delete_memory(None cfg) → False")
    # llm/embedder 없는 dict도 무력화
    check(M.search({"user_id": "a"}, "q", {"foo": 1}) == [], "search(설정 미비) → []")


def test_backend_selection() -> None:
    print("[drop-in] MEMORY_BACKEND env로 백엔드 선택")
    from api.memory import backend as B
    cfg = {"llm": {"model_id": "m", "base_url": "x"}, "embedder": {"model_id": "e", "base_url": "y"}}
    prev = os.environ.get("MEMORY_BACKEND")
    try:
        B._reset_cache()
        os.environ["MEMORY_BACKEND"] = "inmemory"
        b = B.resolve_backend(cfg)
        check(type(b).__name__ == "InMemoryBackend", "env=inmemory → InMemoryBackend 해석(drop-in 기전)")
        B._reset_cache()
        os.environ["MEMORY_BACKEND"] = "nope"
        check(B.resolve_backend(cfg) is None, "미등록 종류 → graceful None")
    finally:
        if prev is None:
            os.environ.pop("MEMORY_BACKEND", None)
        else:
            os.environ["MEMORY_BACKEND"] = prev
        B._reset_cache()


if __name__ == "__main__":
    run_contract("inmemory", make_inmemory)
    run_contract("mem0", make_mem0)
    test_facade_graceful()
    test_backend_selection()
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")
