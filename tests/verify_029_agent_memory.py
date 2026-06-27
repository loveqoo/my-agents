"""스펙 029 검증 — 에이전트 전용 메모리(agent_id) 자가기록 + 관리자 큐레이션 (인프라 불요).

라이브 mem0/Postgres/모델 없이 새 로직의 핵심 불변식을 격리 검증한다:
  1. add(infer=) 플래그가 mem0로 전달 (자가기록·관리자 저작은 infer=False)
  2. **누출 차단**: agent_id 검색에 user_id-only 기억이 잡히지 않음 / agent_id 기억은 타 유저에도 회상
  3. 자가기록 도구(save_agent_knowledge)가 **agent_id-only + infer=False**로만 기록 + calls_sink 트레이스
  4. list/update/delete 헬퍼 라운드트립
  5. chat.py 스코프 분리: recall_scope=agent_id 포함 / add_scope=agent_id 미포함(소스 정적 점검)

라이브 라운드트립(에이전트가 실제로 도구 호출→타세션 회상)은 사용자 브랜치 통합 테스트에서 확인.
실행: .venv/bin/python tests/verify_029_agent_memory.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import memory as M  # noqa: E402
from api import runtime as R  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class FakeMem:
    """단일 축 필터로 store를 거른다(mem0 단축 검색·get_all 모사). 쓰기·수정·삭제 기록·반영."""

    def __init__(self, store: list[dict] | None = None):
        self.store = list(store or [])
        self.added: list[tuple] = []  # (messages, kwargs) — infer 포함

    def search(self, query, filters, top_k):
        (axis, val), = filters.items()
        rows = [r for r in self.store if r.get(axis) == val]
        return {"results": rows[:top_k]}

    def get_all(self, filters):
        (axis, val), = filters.items()
        return {"results": [r for r in self.store if r.get(axis) == val]}

    def add(self, messages, **kwargs):
        self.added.append((messages, kwargs))

    def update(self, memory_id, data):
        for r in self.store:
            if r.get("id") == memory_id:
                r["memory"] = data
                return
        raise KeyError(memory_id)

    def delete(self, memory_id):
        self.store = [r for r in self.store if r.get("id") != memory_id]


def with_mem(mem):
    from api.memory.mem0_backend import Mem0Backend
    backend = Mem0Backend.__new__(Mem0Backend)
    backend._mem = mem
    M.resolve_backend = lambda mem_cfg: backend  # type: ignore[assignment]


# ---------------------------------------------------------------- add infer 전달
def test_add_infer() -> None:
    print("[add] infer 플래그 전달")
    m = FakeMem()
    with_mem(m)
    msgs = [{"role": "user", "content": "보고서는 한 줄 요약으로 시작한다"}]

    M.add({"agent_id": "agtX"}, msgs, {"x": 1}, infer=False)
    check(m.added[-1][1].get("infer") is False, "infer=False 전달")
    check(m.added[-1][1].get("agent_id") == "agtX" and "user_id" not in m.added[-1][1]
          and "run_id" not in m.added[-1][1], "agent_id-only 태깅(user/run 미포함)")

    M.add({"user_id": "alice", "run_id": "s1"}, msgs, {"x": 1})
    check(m.added[-1][1].get("infer") is True, "기본 infer=True(자동 턴 add)")


# ---------------------------------------------------------------- 누출 차단(회상)
def test_leak_isolation() -> None:
    print("[leak] agent_id 검색 격리")
    store = [
        {"id": "u1", "memory": "alice는 비건이다", "score": 0.9, "user_id": "alice"},
        {"id": "ag1", "memory": "이 에이전트는 한국어로 답한다", "score": 0.8, "agent_id": "agtX"},
    ]
    with_mem(FakeMem(store))

    # agent_id만 검색 → 에이전트 기억만, 유저 사실(alice)은 누출 없음.
    hits = M.search({"agent_id": "agtX"}, "q", {"x": 1}, limit=10)
    texts = [h["text"] for h in hits]
    check(any("한국어" in t for t in texts), "agent_id 기억 회상")
    check(not any("비건" in t for t in texts), "user_id-only 기억 누출 없음")
    check(all(h["scope"] == "agent_id" for h in hits), "scope=agent_id 표기")

    # 다른 유저(bob)라도 같은 agent_id면 에이전트 기억 회상(유저 가로지름).
    hits2 = M.search({"user_id": "bob", "agent_id": "agtX"}, "q", {"x": 1}, limit=10)
    check(any("한국어" in h["text"] for h in hits2), "타 유저도 agent_id 기억 회상")
    check(not any("비건" in h["text"] for h in hits2), "타 유저 검색에 alice 사실 없음")


# ---------------------------------------------------------------- 자가기록 도구
def test_self_write_tool() -> None:
    print("[tool] save_agent_knowledge agent_id-only·infer=False")
    m = FakeMem()
    with_mem(m)
    calls: list[dict] = []
    tool = R.build_agent_memory_tool("agtX", {"x": 1}, calls)
    check(tool.name == "save_agent_knowledge", "도구 이름")

    out = tool.func("보고서는 한 줄 요약으로 시작한다")
    check(bool(m.added), "도구가 기억을 저장")
    kw = m.added[-1][1]
    check(kw.get("agent_id") == "agtX", "agent_id로 태깅")
    check("user_id" not in kw and "run_id" not in kw, "user/run 절대 미태깅(누출 차단)")
    check(kw.get("infer") is False, "infer=False 원문 저장")
    check(calls and calls[-1]["tool"] == "save_agent_knowledge", "calls_sink 트레이스 기록")
    check("저장" in out, "확인 메시지 반환")

    before = len(m.added)
    tool.func("   ")  # 공백만 → 저장 안 함
    check(len(m.added) == before, "빈 fact는 저장 안 함")


# ---------------------------------------------------------------- CRUD 헬퍼
def test_crud_helpers() -> None:
    print("[crud] list/update/delete 라운드트립")
    store = [
        {"id": "ag1", "memory": "사실1", "agent_id": "agtX"},
        {"id": "ag2", "memory": "사실2", "agent_id": "agtX"},
        {"id": "other", "memory": "남의 것", "agent_id": "agtY"},
    ]
    m = FakeMem(store)
    with_mem(m)

    rows = M.list_memories({"agent_id": "agtX"}, {"x": 1})
    ids = {r["id"] for r in rows}
    check(ids == {"ag1", "ag2"}, "list_memories는 해당 agent_id만")
    check(all("text" in r and "id" in r for r in rows), "[{id,text}] shape")

    ok = M.update_memory("ag1", "고친 사실", {"x": 1})
    check(ok and any(r["memory"] == "고친 사실" for r in m.store), "update 반영")

    ok2 = M.delete_memory("ag2", {"x": 1})
    check(ok2 and not any(r.get("id") == "ag2" for r in m.store), "delete 반영")

    # 무력화(backend None)면 graceful False/[]
    M.resolve_backend = lambda mem_cfg: None  # type: ignore[assignment]
    check(M.list_memories({"agent_id": "agtX"}, None) == [], "mem None → list []")
    check(M.update_memory("ag1", "x", None) is False, "mem None → update False")
    check(M.delete_memory("ag1", None) is False, "mem None → delete False")


# ---------------------------------------------------------------- chat.py 스코프 분리(정적)
def test_chat_scope_split() -> None:
    print("[chat] recall/add 스코프 분리(소스 정적 점검)")
    src = open(os.path.join(ROOT, "packages", "api", "src", "api", "chat.py"), encoding="utf-8").read()
    # recall_scope는 add_scope에 agent_id를 더한다.
    check(re.search(r"recall_scope\s*=\s*\{\*\*add_scope,\s*\"agent_id\"", src) is not None,
          "recall_scope = {**add_scope, agent_id:…}")
    check('"agent_id": ctx["ext_agent_id"]' in src, "회상 agent_id=ext_agent_id")
    # 자동 턴 add는 add_scope(agent_id 없음)로 호출 — search는 recall_scope.
    check("memory.search, recall_scope" in src, "search는 recall_scope 사용")
    # add 호출은 add_scope 인자로 (자동 턴 저장)
    check(re.search(r"memory\.add,\s*\n\s*add_scope", src) is not None,
          "자동 add는 add_scope(agent_id 미포함) 사용")
    # add_scope 정의에 agent_id가 들어가지 않음
    check(re.search(r"add_scope\s*=\s*\{\"user_id\":[^}]*\}", src) is not None
          and "agent_id" not in re.search(r"add_scope\s*=\s*\{[^}]*\}", src).group(0),
          "add_scope에 agent_id 없음(누출 차단)")


# ------------------------------------------------- 소유권 가드(정적, 비판리뷰 HIGH)
def test_owner_guard() -> None:
    print("[guard] admin update/delete가 _assert_owns로 소유권 강제(소스 정적 점검)")
    src = open(os.path.join(ROOT, "packages", "api", "src", "api", "agents.py"), encoding="utf-8").read()
    # mem_id를 받는 두 변조 엔드포인트는 mem0 호출 전에 _assert_owns를 통과해야 한다.
    # (공유 pgvector라 path agent_id 없이는 타 에이전트/유저 행을 변조 가능 — 라이브로 404 확인됨)
    check(src.count("await _assert_owns(agent, mem_id, mem_cfg)") >= 2,
          "update/delete 모두 _assert_owns 호출")
    upd = src[src.index("async def update_agent_memory"):src.index("async def delete_agent_memory")]
    check("_assert_owns" in upd and upd.index("_assert_owns") < upd.index("memory.update_memory"),
          "update: 소유권 확인이 mem0.update보다 먼저")
    dele = src[src.index("async def delete_agent_memory"):]
    check("_assert_owns" in dele and dele.index("_assert_owns") < dele.index("memory.delete_memory"),
          "delete: 소유권 확인이 mem0.delete보다 먼저")


if __name__ == "__main__":
    test_add_infer()
    test_leak_isolation()
    test_self_write_tool()
    test_crud_helpers()
    test_chat_scope_split()
    test_owner_guard()
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")
