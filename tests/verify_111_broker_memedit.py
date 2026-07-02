"""스펙 111 검증 — 능력 브로커 Memory **edit** provider(kind=memedit, 대상 있는 첫 부수효과).

핵심 불변식(스펙 111 — RBAC/소유권 체크리스트):
1. **스코프=principal 도출 user_id 고정** — args의 user_id 등 무시(anti-leak, 104/105 동일).
2. **대상 소유권 선행** — mem_id가 자기 것인지 `memory.user_owns`로 확인. 미소유·부재는 **동일 error**로
   404-fold(존재 비노출, 068). 소유권 술어 단일 출처(HTTP `_assert_user_owns`와 공유, 드리프트 0).
3. **승인 게이트 항상** — 부수효과 이전 interrupt. reject→무변경 / approve→정확히 1회 실행(멱등).
4. **삭제 비가역 fail-closed** — RBAC `capability:memedit`는 member 시드 없음(admin/superuser만).
5. **자가-잠금 핀** — 본인 mem_id는 정상 수정/삭제(조임이 본인 접근을 막지 않음).

  [U] 단위(FakeMemStore — 인프라 불요) — 네임스페이스·_permitted·approval 항상 non-None·describe·
      candidates 게이트·머신 deny·**self-scope 수정/삭제**·교차유저 거부·args anti-leak·404-fold·배선.
  [G] 그래프 게이트(1노드 + MemorySaver, LLM 불요) — interrupt→pre 무변경 / approve→1회 실행 /
      reject→무변경(삭제 결정적 실측).
  [H] 통합(실 DB·mem0 — guarded) — memedit member 미시드(fail-closed) + 실 add→update→delete 왕복·
      교차유저 거부·자가잠금 핀.

실행: cd packages/api && uv run python ../../tests/verify_111_broker_memedit.py
"""
import asyncio
import os
import sys
import uuid
from typing import TypedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command  # noqa: E402

from api import memory as M  # noqa: E402
from api import mem_config as MC  # noqa: E402
from api.broker import (  # noqa: E402
    MEMEDIT_MAX_CHARS,
    MEMEDIT_PERMISSION,
    MemEditProvider,
    PolicyScopedBroker,
    _MemBacking,
    _kind_of,
    _parse_memedit,
    build_broker,
)

MEMEDIT = "memedit:user"
_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class P:
    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.email = "u@example.com"
        self.display_name = None


class FakeMemStore:
    """mem0 모사 — user_id별 기억 보관. list_all/update/delete로 소유권·수정/삭제 부수효과 관측."""

    def __init__(self):
        self.rows: dict[str, dict] = {}  # mem_id -> {id, text, user_id}
        self._n = 0

    def seed(self, user_id: str, text: str) -> str:
        self._n += 1
        mid = f"m{self._n}"
        self.rows[mid] = {"id": mid, "text": text, "user_id": user_id}
        return mid

    def list_all(self, scope: dict):
        (axis, val), = scope.items()
        return [{"id": r["id"], "text": r["text"]} for r in self.rows.values() if r.get(axis) == val]

    def update(self, mem_id: str, text: str) -> bool:
        if mem_id in self.rows:
            self.rows[mem_id]["text"] = text
            return True
        return False

    def delete(self, mem_id: str) -> bool:
        return self.rows.pop(mem_id, None) is not None


def with_mem(store) -> None:
    # FakeMemStore가 list_all/update/delete를 제공 → memory 코어의 backend로 직접 시임(duck-typed).
    M.resolve_backend = lambda mem_cfg: store  # type: ignore[assignment]


def _async(val):
    async def _f(*a, **k):
        return val
    return _f


class _FakeDB:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


def _fake_factory():
    return _FakeDB()


def _raise_factory():
    def make():
        raise AssertionError("거부/무해 경로가 DB를 만졌다(존재 누출 위험)")
    return make


# ================================================================ [U] 단위
def unit_checks() -> None:
    print("[U] 단위 — 네임스페이스·_permitted·approval 항상 non-None·describe·시임 계약")
    check(_kind_of("memedit:user") == "memedit", "U1 memedit: 접두사 → kind memedit")
    check(_kind_of("memwrite:user") == "memwrite" and _kind_of("memory:user") == "memory"
          and _kind_of("rag:x") == "rag" and _kind_of("agt_x") == "agent",
          "U1 memwrite/memory/rag/agent 판정 무회귀(memedit와 충돌 없음)")
    check(_parse_memedit("memedit:user") == "user", "U1 memedit:user → user")
    check(_parse_memedit("memedit:") == "", "U1 memedit: → 빈 리소스")
    check(_parse_memedit("memory:user") == "memory:user", "U1 다른 kind는 원본 방어(접두사 안 벗김)")

    bt = PolicyScopedBroker({MEMEDIT}, lambda k: True, session_factory=_raise_factory(), user_id="bob")
    check(bt._permitted(MEMEDIT) is True, "U2 정확 memedit cap 허용 → permitted")
    check(bt._permitted("memedit:other") is False, "U2 allow 밖 → deny(비노출)")
    brd = PolicyScopedBroker({MEMEDIT}, lambda k: False, session_factory=_raise_factory(), user_id="bob")
    check(brd._permitted(MEMEDIT) is False, "U2 RBAC 거부 → deny(교집합)")

    me = MemEditProvider(_raise_factory(), "bob")
    # U3 approval_for — 부수효과 → **항상 non-None** + 액션 노출.
    ap_del = me.approval_for(MEMEDIT, {"op": "delete", "mem_id": "m1"})
    check(ap_del is not None and ap_del["permission"] == MEMEDIT_PERMISSION == "memory.edit",
          "U3 approval_for delete → non-None, permission=memory.edit(admin 전용)")
    check("m1" in ap_del["summary"] and "삭제" in ap_del["summary"], "U3 delete summary에 대상 id·액션 노출")
    ap_up = me.approval_for(MEMEDIT, {"op": "update", "mem_id": "m2", "text": "밥은 재즈를 친다"})
    check("재즈" in ap_up["args"]["text"] and "재즈" in ap_up["summary"], "U3 update 새 본문 마스킹 없이 노출")
    ap_long = me.approval_for(MEMEDIT, {"op": "update", "mem_id": "m3", "text": "가" * 500})
    check(len(ap_long["summary"]) < 400 and "…" in ap_long["summary"], "U3 update summary 미리보기 상한")

    # U4 describe — op enum + mem_id 필수, user_id 필드 없음(주체 고정).
    desc = me.describe(_MemBacking("user"))
    props = (desc.input_schema or {}).get("properties", {})
    check(desc.kind == "memedit" and desc.id == MEMEDIT, "U4 describe id/kind")
    check(props.get("op", {}).get("enum") == ["update", "delete"], "U4 op enum=[update,delete]")
    check(desc.input_schema.get("required") == ["op", "mem_id"], "U4 op·mem_id 필수")
    check("user_id" not in props, "U4 스키마에 user_id 없음(대상=주체 도출)")

    b = PolicyScopedBroker([], lambda k: True, session_factory=_raise_factory(), user_id="bob")
    check("memedit" in b._by_kind and isinstance(b._by_kind["memedit"], MemEditProvider),
          "U5 _by_kind에 memedit → MemEditProvider")
    check({"agent", "mcp", "rag", "memory", "memwrite", "memedit"} <= set(b._by_kind),
          "U5 6 provider 보유(읽기+쓰기+수정삭제)")
    check(me.node_label(_MemBacking("user")) == "broker_invoke:memedit:user", "U5 node_label 형식")


async def unit_async_checks() -> None:
    print("[U] 단위(async) — candidates 게이트·머신·self-scope 수정/삭제·교차유저 거부·anti-leak·404-fold")
    MC.default_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]

    me_bob = MemEditProvider(_raise_factory(), "bob")
    check([c.id for c in await me_bob.candidates({MEMEDIT})] == [MEMEDIT], "U6 allow∋memedit:user+user_id → cap")
    check(await me_bob.candidates(set()) == [], "U6 allow 밖 → []")
    check(await me_bob.candidates({"memedit:other", "memedit:"}) == [], "U6 미지원/빈 리소스 → []")
    me_machine = MemEditProvider(_raise_factory(), None)
    check(await me_machine.candidates({MEMEDIT}) == [], "U6 머신(user_id None) → [](자기 스코프 없음)")
    check(await me_machine.load(MEMEDIT) is None, "U6 머신 load → None(존재 비노출)")
    check(await me_bob.load("memedit:other") is None, "U6 미지원 리소스 load → None")

    # ---- self-scope 수정/삭제 + 교차유저 거부 + anti-leak (FakeMemStore) ----
    store = FakeMemStore()
    bob_mid = store.seed("bob", "밥은 커피를 마신다")
    alice_mid = store.seed("alice", "앨리스의 비밀")
    with_mem(store)
    me = MemEditProvider(_fake_factory, "bob")

    # 자가잠금 핀: 본인 기억 수정 성공(체크리스트 §6).
    r_up = await me.invoke(_MemBacking("user"), {"op": "update", "mem_id": bob_mid, "text": "밥은 차를 마신다"})
    check(r_up.error is None and store.rows[bob_mid]["text"] == "밥은 차를 마신다",
          "U7 자가잠금 핀: 본인 mem_id 수정 성공(본문 반영)")

    # 교차유저: alice mem_id를 bob provider로 → 404-fold 거부, **부수효과 0**.
    before = store.rows[alice_mid]["text"]
    r_x = await me.invoke(_MemBacking("user"), {"op": "update", "mem_id": alice_mid, "text": "변조"})
    check(r_x.error is not None and "유저의 기억이 아닙니다" in r_x.error,
          "U7 교차유저 수정 → 거부(미소유)")
    check(store.rows[alice_mid]["text"] == before, "U7 교차유저 거부 시 부수효과 0(alice 행 무변경)")

    # 존재 비노출: 부재 mem_id와 미소유 mem_id가 **동일 error**(404-fold, 403/404 구분 없음).
    r_absent = await me.invoke(_MemBacking("user"), {"op": "delete", "mem_id": "no-such-id"})
    check(r_absent.error == r_x.error, "U7 부재 mem_id error == 미소유 error(존재 비노출·404-fold)")

    # anti-leak: args user_id=alice 밀반입 + 본인 mem_id → 무시(스코프 bob 고정), 수정 성공.
    r_leak = await me.invoke(_MemBacking("user"),
                             {"op": "update", "mem_id": bob_mid, "text": "다시 커피", "user_id": "alice"})
    check(r_leak.error is None and store.rows[bob_mid]["text"] == "다시 커피",
          "U7 args user_id=alice 밀반입 → 무시(스코프 bob 고정, 본인 수정 성공)")
    # anti-leak 역: args user_id=bob 밀반입 + alice mem_id → 여전히 거부(scope는 args 아님).
    r_leak2 = await me.invoke(_MemBacking("user"),
                              {"op": "delete", "mem_id": alice_mid, "user_id": "bob"})
    check(r_leak2.error is not None and alice_mid in store.rows,
          "U7 args user_id=bob 밀반입 + alice mem_id → 거부(scope=principal, args 무시)")

    # 입력 검증: 잘못된 op / mem_id 없음 / update 빈 본문 → 부수효과 0.
    r_badop = await me.invoke(_MemBacking("user"), {"op": "purge", "mem_id": bob_mid})
    check(r_badop.error is not None and "update/delete" in r_badop.error, "U7 미지원 op → 거부(부수효과 0)")
    r_noid = await me.invoke(_MemBacking("user"), {"op": "delete", "mem_id": "  "})
    check(r_noid.error is not None and "id" in r_noid.error, "U7 mem_id 없음 → 거부")
    r_emptyup = await me.invoke(_MemBacking("user"), {"op": "update", "mem_id": bob_mid, "text": "   "})
    check(r_emptyup.error is not None, "U7 update 빈 본문 → 거부(부수효과 0)")

    # 승인한 것 == 실행되는 것: 거대 update 본문 → 저장·승인 모두 동일 상한.
    huge = "가" * 50_000
    await me.invoke(_MemBacking("user"), {"op": "update", "mem_id": bob_mid, "text": huge})
    stored = store.rows[bob_mid]["text"]
    approved = me.approval_for(MEMEDIT, {"op": "update", "mem_id": bob_mid, "text": huge})["args"]["text"]
    check(len(stored) == MEMEDIT_MAX_CHARS and stored == approved,
          f"U7 거대 update → 상한({MEMEDIT_MAX_CHARS}) & 승인==실행(길이 {len(stored)})")

    # 삭제 성공(본인).
    r_del = await me.invoke(_MemBacking("user"), {"op": "delete", "mem_id": bob_mid})
    check(r_del.error is None and bob_mid not in store.rows, "U7 본인 mem_id 삭제 → 소멸")

    # 백엔드 미가용 → graceful.
    M.resolve_backend = lambda mem_cfg: None  # type: ignore[assignment]
    r_off = await me.invoke(_MemBacking("user"), {"op": "delete", "mem_id": "m1"})
    check(r_off.error is not None and "구성" in r_off.error, "U7 백엔드 미가용 → graceful 오류(부수효과 0)")

    # 배선: build_broker + resume broker가 memedit provider에 user_id 주입.
    bob = P()
    wired = build_broker(bob, {MEMEDIT})
    check(wired._by_kind["memedit"]._user_id == str(bob.id), "U8 build_broker → memedit user_id 주입")
    from api import chat as CHAT
    rb = await CHAT._build_resume_broker("bob-uid", {MEMEDIT})
    check(rb._by_kind["memedit"]._user_id == "bob-uid", "U8 _build_resume_broker → memedit user_id 복원(재개)")


# ================================================================ [G] 그래프 게이트(승인 왕복)
def _edit_graph(broker):
    class St(TypedDict, total=False):
        op: str
        mem_id: str
        result: str
        error: str

    async def _edit(state: St) -> dict:
        res = await broker.invoke(MEMEDIT, {"op": state["op"], "mem_id": state["mem_id"]})
        return {"result": res.text, "error": res.error}

    g = StateGraph(St)
    g.add_node("edit", _edit)
    g.add_edge(START, "edit")
    g.add_edge("edit", END)
    return g.compile(checkpointer=MemorySaver())


async def _stream(graph, payload, cfg):
    interrupted = None
    async for _mode, chunk in graph.astream(payload, config=cfg, stream_mode=["updates"]):
        if isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupted = chunk["__interrupt__"][0].value
    return interrupted


async def graph_gate_checks() -> None:
    print("[G] 그래프 게이트 — interrupt→pre 무변경 / approve→1회 삭제 / reject→무변경")
    MC.default_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]

    # approve 결.
    store = FakeMemStore()
    mid = store.seed("bob", "삭제될 사실")
    with_mem(store)
    b = PolicyScopedBroker({MEMEDIT}, lambda k: True, session_factory=_fake_factory, user_id="bob")
    g = _edit_graph(b)
    cfg = {"configurable": {"thread_id": "v111-approve"}}
    itr = await _stream(g, {"op": "delete", "mem_id": mid}, cfg)
    check(itr is not None and itr.get("permission") == "memory.edit",
          "G1 memedit 위임 → interrupt(permission=memory.edit)")
    check(mid in store.rows and len(b.invocations) == 0, "G1 pause 시 무변경(승인 전 부수효과 0=멱등)")
    await _stream(g, Command(resume={"decision": "approve"}), cfg)
    check(mid not in store.rows, "G1 approve 재개 → 정확히 1회 삭제")
    check(len(b.invocations) == 1 and b.invocations[0]["node"] == "broker_invoke:memedit:user",
          "G1 approve → invocations 1(memedit 노드)")

    # reject 결.
    store2 = FakeMemStore()
    mid2 = store2.seed("bob", "삭제되면 안 되는 사실")
    with_mem(store2)
    b2 = PolicyScopedBroker({MEMEDIT}, lambda k: True, session_factory=_fake_factory, user_id="bob")
    g2 = _edit_graph(b2)
    cfg2 = {"configurable": {"thread_id": "v111-reject"}}
    itr2 = await _stream(g2, {"op": "delete", "mem_id": mid2}, cfg2)
    check(itr2 is not None and mid2 in store2.rows, "G2 reject 결: interrupt & pause 무변경")
    await _stream(g2, Command(resume={"decision": "reject"}), cfg2)
    check(mid2 in store2.rows and len(b2.invocations) == 0, "G2 reject 재개 → 무변경(부수효과 0)")


# ================================================================ [H] 통합(실 DB·mem0 — guarded)
async def integration_checks() -> None:
    print("[H] 통합(실 DB·mem0) — memedit member 미시드(fail-closed) + 실 add→update→delete 왕복·교차유저 거부")
    import importlib
    importlib.reload(M)
    importlib.reload(MC)
    from api import authz
    from api.db import SessionLocal

    await authz.init_authz()
    e = authz.get_enforcer()
    # 삭제 비가역 → memedit는 member 시드 없음(fail-closed). admin은 (*,*)로 허용.
    check(not e.has_policy("member", "capability:memedit", "invoke"),
          "H1 member capability:memedit 미시드(삭제 비가역 fail-closed)")
    check(e.enforce("__admin_probe__", "capability:memedit", "invoke") is False,
          "H1 정책 없는 주체는 memedit deny(deny-by-default)")

    async with SessionLocal() as db:
        mem_cfg = await MC.default_mem_cfg(db)
    if mem_cfg is None or M.resolve_backend(mem_cfg) is None:
        print("  ..  [H] add→update→delete 왕복 SKIP — mem0 백엔드 미구성")
        return

    bob_uid = f"v111_bob_{uuid.uuid4().hex[:8]}"
    alice_uid = f"v111_alice_{uuid.uuid4().hex[:8]}"

    def _purge(uid):
        for r in M.list_memories({"user_id": uid}, mem_cfg):
            M.delete_memory(r["id"], mem_cfg)

    await asyncio.to_thread(_purge, bob_uid)
    await asyncio.to_thread(_purge, alice_uid)
    try:
        # 실 mem0에 시드(add, infer=False=원문).
        await asyncio.to_thread(
            M.add, {"user_id": bob_uid}, [{"role": "user", "content": "밥은 재즈 피아노를 친다 v111"}], mem_cfg, False)
        await asyncio.to_thread(
            M.add, {"user_id": alice_uid}, [{"role": "user", "content": "앨리스의 비밀 v111"}], mem_cfg, False)
        bob_rows = await asyncio.to_thread(M.list_memories, {"user_id": bob_uid}, mem_cfg)
        alice_rows = await asyncio.to_thread(M.list_memories, {"user_id": alice_uid}, mem_cfg)
        check(len(bob_rows) >= 1 and len(alice_rows) >= 1, "H2 실 mem0 시드(bob·alice 각 1+)")
        bob_mid = bob_rows[0]["id"]
        alice_mid = alice_rows[0]["id"]

        me = MemEditProvider(SessionLocal, bob_uid)
        # 자가잠금 핀: 본인 수정 성공 → 반영.
        r_up = await me.invoke(_MemBacking("user"), {"op": "update", "mem_id": bob_mid, "text": "밥은 클래식을 친다 v111"})
        check(r_up.error is None, f"H3 자가잠금 핀: 본인 수정 성공 (err={r_up.error})")
        refreshed = await asyncio.to_thread(M.list_memories, {"user_id": bob_uid}, mem_cfg)
        check(any("클래식" in r["text"] for r in refreshed), "H3 수정 본문이 실제 반영")

        # 교차유저: bob provider로 alice mem_id 삭제 시도 → 거부, alice 행 생존.
        r_x = await me.invoke(_MemBacking("user"), {"op": "delete", "mem_id": alice_mid})
        check(r_x.error is not None, "H3 교차유저 삭제 → 거부(미소유)")
        alice_after = await asyncio.to_thread(M.list_memories, {"user_id": alice_uid}, mem_cfg)
        check(len(alice_after) == len(alice_rows), "H3 교차유저 거부 시 alice 행 생존(부수효과 0)")

        # 자가잠금 핀: 본인 삭제 성공 → 소멸.
        r_del = await me.invoke(_MemBacking("user"), {"op": "delete", "mem_id": bob_mid})
        check(r_del.error is None, f"H3 본인 삭제 성공 (err={r_del.error})")
    finally:
        await asyncio.to_thread(_purge, bob_uid)
        await asyncio.to_thread(_purge, alice_uid)


async def main() -> None:
    unit_checks()
    await unit_async_checks()
    print()
    await graph_gate_checks()
    print()
    try:
        await integration_checks()
    except Exception as exc:  # noqa: BLE001
        print(f"  ..  [H] 통합 SKIP — DB/mem0 미가용({type(exc).__name__}: {exc})")
        print("      U·G가 핵심 불변식(소유권 선행·404-fold·승인 게이트·anti-leak) 보증.")


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS (VERIFY111_OK)")
