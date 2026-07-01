"""스펙 105 검증 — 능력 브로커 Memory **write** provider(kind=memwrite, 첫 부수효과·승인 게이트).

핵심 불변식(스펙 105):
1. **쓰기 축=user_id(자기)만·principal 바인딩** — `{"user_id": self._user_id}`에만 쓴다(agent_id 금지=051
   누출 축). user_id는 cap_id·args가 아니라 principal 도출값(104와 동일) → 남의 기억에 쓸 방법 없음.
2. **승인 게이트** — `approval_for`가 **항상 non-None**(읽기와 정반대). 브로커가 `memory.add`(부수효과)
   이전 `interrupt`로 멈추고 승인돼야 저장. **reject→무저장 / approve→정확히 1회 저장**(멱등, §7).
3. **저장=승인한 원문**(infer=False), 승인 payload는 저장될 사실을 **마스킹 없이** 노출(승인 가시성).
4. **소유자 self-승인 기본**(066) — `member`가 자기 `memory.write` 승인 직접 결정. `data.delete`는 여전히 admin.

  [U] 단위(FakeMem-add — 인프라 불요) — 네임스페이스·_permitted·approval 항상 non-None·describe·candidates
      게이트·머신 deny·**self-scope 쓰기**(direct provider.invoke)·빈 text 무저장·args anti-leak·배선.
  [G] 그래프 게이트(최소 1노드 graph + MemorySaver, LLM 불요) — **interrupt→pre 무저장 / approve→1회
      저장(bob scope) / reject→무저장**을 결정적으로 실측(broker.invoke 승인 흐름).
  [H] 통합(실 DB·mem0 — guarded) — self-approve 정책 시드(member memory.write / data.delete 아님) +
      실 mem0 쓰기→읽기(104) 왕복·교차유저 무저장.

실행: .venv/bin/python tests/verify_105_broker_memwrite.py
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
    MEMWRITE_PERMISSION,
    MemoryWriteProvider,
    PolicyScopedBroker,
    _MemBacking,
    _kind_of,
    _parse_memwrite,
    build_broker,
)

MEMWRITE = "memwrite:user"
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


class FakeMemAdd:
    """mem0 검색+쓰기 모사 — add를 (scope kwargs, messages)로 기록해 부수효과를 결정적으로 관측.
    search는 기록된 add를 user_id 축으로 필터(쓰기→읽기 왕복·교차유저 격리 실증)."""

    def __init__(self):
        self.adds: list[tuple[dict, list]] = []

    def add(self, messages, infer, **kwargs):
        self.adds.append((kwargs, messages))

    def search(self, query, filters, top_k):
        (axis, val), = filters.items()
        rows = []
        for kw, msgs in self.adds:
            if kw.get(axis) == val:
                for m in msgs:
                    rows.append({"id": f"m{len(rows)}", "memory": m["content"], "score": 1.0, axis: val})
        return {"results": rows[:top_k]}

    def get_all(self, filters):
        return self.search("", filters, 100)


def with_mem(mem) -> None:
    from api.memory.mem0_backend import Mem0Backend
    backend = Mem0Backend.__new__(Mem0Backend)
    backend._mem = mem
    M.resolve_backend = lambda mem_cfg: backend  # type: ignore[assignment]


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
    print("[U] 단위 — 네임스페이스·_permitted·approval 항상 non-None·describe·candidates·시임 계약")
    check(_kind_of("memwrite:user") == "memwrite", "U1 memwrite: 접두사 → kind memwrite")
    check(_kind_of("memory:user") == "memory" and _kind_of("rag:x") == "rag" and _kind_of("agt_x") == "agent",
          "U1 memory/rag/agent 판정 무회귀(memwrite와 충돌 없음)")
    check(_parse_memwrite("memwrite:user") == "user", "U1 memwrite:user → user")
    check(_parse_memwrite("memwrite:") == "", "U1 memwrite: → 빈 리소스")
    check(_parse_memwrite("memory:user") == "memory:user", "U1 다른 kind는 원본 방어(memory: 접두사 안 벗김)")

    bt = PolicyScopedBroker({MEMWRITE}, lambda k: True, session_factory=_raise_factory(), user_id="bob")
    check(bt._permitted(MEMWRITE) is True, "U2 정확 memwrite cap 허용 → permitted")
    check(bt._permitted("memwrite:other") is False, "U2 allow 밖 → deny(비노출)")
    brd = PolicyScopedBroker({MEMWRITE}, lambda k: False, session_factory=_raise_factory(), user_id="bob")
    check(brd._permitted(MEMWRITE) is False, "U2 RBAC 거부 → deny(교집합)")

    mw = MemoryWriteProvider(_raise_factory(), "bob")
    # U3 approval_for — 쓰기=부수효과 → **항상 non-None**(읽기와 정반대) + 저장될 사실 노출.
    ap = mw.approval_for(MEMWRITE, {"text": "밥은 재즈를 친다"})
    check(ap is not None, "U3 approval_for → 항상 non-None(쓰기=부수효과, 읽기와 정반대)")
    check(ap["permission"] == MEMWRITE_PERMISSION == "memory.write", "U3 permission=memory.write(066 self-approve)")
    check("재즈" in ap["args"]["text"] and "재즈" in ap["summary"], "U3 저장될 사실을 마스킹 없이 노출(승인 가시성)")
    ap_long = mw.approval_for(MEMWRITE, {"text": "가" * 500})
    check(len(ap_long["summary"]) < 400 and "…" in ap_long["summary"], "U3 summary 미리보기 상한(거대 사실)")

    # U4 describe — text 필수, user_id 필드 없음(주체 고정).
    desc = mw.describe(_MemBacking("user"))
    props = (desc.input_schema or {}).get("properties", {})
    check(desc.kind == "memwrite" and desc.id == MEMWRITE, "U4 describe id/kind")
    check("text" in props and desc.input_schema.get("required") == ["text"], "U4 text 필수")
    check("user_id" not in props, "U4 스키마에 user_id 없음(대상=주체 도출)")

    b = PolicyScopedBroker([], lambda k: True, session_factory=_raise_factory(), user_id="bob")
    check("memwrite" in b._by_kind and isinstance(b._by_kind["memwrite"], MemoryWriteProvider),
          "U5 _by_kind에 memwrite → MemoryWriteProvider")
    check({"agent", "mcp", "rag", "memory", "memwrite"} <= set(b._by_kind), "U5 5 provider 보유(읽기+쓰기 분리)")
    check(mw.node_label(_MemBacking("user")) == "broker_invoke:memwrite:user", "U5 node_label 형식")


async def unit_async_checks() -> None:
    print("[U] 단위(async) — candidates 게이트·머신·self-scope 쓰기·빈 무저장·args anti-leak·배선")
    MC.default_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]

    mw_bob = MemoryWriteProvider(_raise_factory(), "bob")
    check([c.id for c in await mw_bob.candidates({MEMWRITE})] == [MEMWRITE], "U6 allow∋memwrite:user+user_id → cap")
    check(await mw_bob.candidates(set()) == [], "U6 allow 밖 → []")
    check(await mw_bob.candidates({"memwrite:other", "memwrite:"}) == [], "U6 미지원/빈 리소스 → []")
    mw_machine = MemoryWriteProvider(_raise_factory(), None)
    check(await mw_machine.candidates({MEMWRITE}) == [], "U6 머신(user_id None) → [](자기 스코프 없음)")
    check(await mw_machine.load(MEMWRITE) is None, "U6 머신 load → None(존재 비노출)")
    check(await mw_bob.load("memwrite:other") is None, "U6 미지원 리소스 load → None")

    # ---- self-scope 쓰기(direct provider.invoke) + 교차유저 격리 + anti-leak ----
    fake = FakeMemAdd()
    with_mem(fake)
    mw = MemoryWriteProvider(_fake_factory, "bob")
    res = await mw.invoke(_MemBacking("user"), {"text": "밥은 재즈를 친다"})
    check(res.error is None and "저장했습니다" in res.text, "U7 invoke → 저장 확인 텍스트")
    check(len(fake.adds) == 1 and fake.adds[0][0] == {"user_id": "bob"},
          f"U7 memory.add가 자기 user_id 스코프에만(got {fake.adds[0][0] if fake.adds else None})")
    check(fake.adds[0][1][0]["content"] == "밥은 재즈를 친다", "U7 저장 원문=입력 그대로(infer=False)")

    # args의 user_id/agent_id 밀반입 → 무시(스코프는 주체 도출값만).
    fake.adds.clear()
    await mw.invoke(_MemBacking("user"), {"text": "x", "user_id": "alice", "agent_id": "agtX"})
    check(fake.adds[0][0] == {"user_id": "bob"}, "U7 args user_id=alice·agent_id 밀반입 → bob 스코프만(무시)")

    # 빈 text → 무저장(부수효과 0).
    fake.adds.clear()
    r_empty = await mw.invoke(_MemBacking("user"), {"text": "   "})
    check(r_empty.error is not None and len(fake.adds) == 0, "U7 빈 text → 무저장(부수효과 0)")

    # 거대 text(적대 리뷰 105 P2) → 저장·승인 모두 상한, 그리고 **둘이 일치**(승인한 것==저장되는 것).
    from api.broker import MEMWRITE_MAX_CHARS
    fake.adds.clear()
    huge = "가" * 50_000
    await mw.invoke(_MemBacking("user"), {"text": huge})
    stored = fake.adds[0][1][0]["content"]
    approved = mw.approval_for(MEMWRITE, {"text": huge})["args"]["text"]
    check(len(stored) == MEMWRITE_MAX_CHARS, f"U7 거대 text → 저장 상한({MEMWRITE_MAX_CHARS}) (got {len(stored)})")
    check(stored == approved, "U7 승인 args.text == 저장 text(동일 상한 = 승인한 것==저장되는 것)")

    # 백엔드 미가용 → graceful 무저장.
    M.resolve_backend = lambda mem_cfg: None  # type: ignore[assignment]
    r_off = await mw.invoke(_MemBacking("user"), {"text": "y"})
    check(r_off.error is not None and "구성" in r_off.error, "U7 백엔드 미가용 → graceful 오류(무저장)")

    # 배선: build_broker + resume broker가 memwrite provider에 user_id 주입.
    bob = P()
    wired = build_broker(bob, {MEMWRITE})
    check(wired._by_kind["memwrite"]._user_id == str(bob.id), "U8 build_broker → memwrite provider user_id 주입")
    from api import chat as CHAT
    rb = await CHAT._build_resume_broker("bob-uid", {MEMWRITE})
    check(rb._by_kind["memwrite"]._user_id == "bob-uid", "U8 _build_resume_broker → memwrite user_id 복원(재개)")


# ================================================================ [G] 그래프 게이트(승인 왕복)
def _write_graph(broker):
    """broker.invoke("memwrite:user")를 부르는 최소 1노드 그래프(LLM 불요). interrupt가 여기서 발화."""
    class St(TypedDict, total=False):
        fact: str
        result: str
        error: str

    async def _write(state: St) -> dict:
        res = await broker.invoke(MEMWRITE, {"text": state["fact"]})
        return {"result": res.text, "error": res.error}

    g = StateGraph(St)
    g.add_node("write", _write)
    g.add_edge(START, "write")
    g.add_edge("write", END)
    return g.compile(checkpointer=MemorySaver())


async def _stream(graph, payload, cfg):
    interrupted = None
    async for mode, chunk in graph.astream(payload, config=cfg, stream_mode=["updates"]):
        if isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupted = chunk["__interrupt__"][0].value
    return interrupted


async def graph_gate_checks() -> None:
    print("[G] 그래프 게이트 — interrupt→pre 무저장 / approve→1회 저장(bob) / reject→무저장")
    MC.default_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]

    # approve 결.
    fake = FakeMemAdd()
    with_mem(fake)
    b = PolicyScopedBroker({MEMWRITE}, lambda k: True, session_factory=_fake_factory, user_id="bob")
    g = _write_graph(b)
    cfg = {"configurable": {"thread_id": "v105-approve"}}
    itr = await _stream(g, {"fact": "밥은 재즈를 친다"}, cfg)
    check(itr is not None and itr.get("permission") == "memory.write",
          "G1 memwrite 위임 → interrupt(permission=memory.write)")
    check(len(fake.adds) == 0 and len(b.invocations) == 0, "G1 pause 시 무저장(승인 전 부수효과 0=멱등)")
    await _stream(g, Command(resume={"decision": "approve"}), cfg)
    check(len(fake.adds) == 1 and fake.adds[0][0] == {"user_id": "bob"},
          f"G1 approve 재개 → 정확히 1회 저장(bob scope) (adds={len(fake.adds)})")
    check(len(b.invocations) == 1 and b.invocations[0]["node"] == "broker_invoke:memwrite:user",
          "G1 approve → invocations 1(memwrite 노드)")

    # reject 결.
    fake2 = FakeMemAdd()
    with_mem(fake2)
    b2 = PolicyScopedBroker({MEMWRITE}, lambda k: True, session_factory=_fake_factory, user_id="bob")
    g2 = _write_graph(b2)
    cfg2 = {"configurable": {"thread_id": "v105-reject"}}
    itr2 = await _stream(g2, {"fact": "저장되면 안 되는 사실"}, cfg2)
    check(itr2 is not None, "G2 reject 결: memwrite 위임 → interrupt")
    check(len(fake2.adds) == 0, "G2 pause 시 무저장")
    await _stream(g2, Command(resume={"decision": "reject"}), cfg2)
    check(len(fake2.adds) == 0 and len(b2.invocations) == 0,
          "G2 reject 재개 → 무저장(부수효과 0, 거부 안전)")


# ================================================================ [H] 통합(실 DB·mem0 — guarded)
async def integration_checks() -> None:
    print("[H] 통합(실 DB·mem0) — self-approve 정책 시드 + 실 쓰기→읽기 왕복·교차유저 무저장")
    import importlib
    importlib.reload(M)
    importlib.reload(MC)
    from api import authz
    from api.broker import MemoryProvider
    from api.db import SessionLocal

    await authz.init_authz()
    e = authz.get_enforcer()
    # self-approve 정책: member는 memory.write 자기 승인 가능, data.delete는 여전히 불가(민감도 구분).
    check(e.has_policy("member", "memory.write", "self_approve"),
          "H1 member memory.write self_approve 정책 시드됨(소유자 본인 승인 기본)")
    check(not e.has_policy("member", "data.delete", "self_approve"),
          "H1 data.delete는 self_approve 아님(민감 perm=admin 전용, 민감도 구분 무회귀)")

    async with SessionLocal() as db:
        mem_cfg = await MC.default_mem_cfg(db)
    if mem_cfg is None or M.resolve_backend(mem_cfg) is None:
        print("  ..  [H] 쓰기→읽기 왕복 SKIP — mem0 백엔드 미구성")
        return

    bob_uid = f"v105_bob_{uuid.uuid4().hex[:8]}"
    alice_uid = f"v105_alice_{uuid.uuid4().hex[:8]}"
    fact = "밥은 재즈 피아노를 친다는 사실 v105"

    def _purge(uid):
        for r in M.list_memories({"user_id": uid}, mem_cfg):
            M.delete_memory(r["id"], mem_cfg)

    await asyncio.to_thread(_purge, bob_uid)
    await asyncio.to_thread(_purge, alice_uid)
    try:
        # 실 provider.invoke(승인 후 경로) → 실 mem0에 저장(bob 스코프).
        mw = MemoryWriteProvider(SessionLocal, bob_uid)
        res = await mw.invoke(_MemBacking("user"), {"text": fact})
        check(res.error is None, f"H2 실 mem0 저장 → 에러 없음 (err={res.error})")

        # 쓰기→읽기 왕복: MemoryProvider(104)로 bob 스코프 회상 → 그 사실 있음.
        mr_bob = MemoryProvider(SessionLocal, bob_uid)
        rb = await mr_bob.invoke(_MemBacking("user"), {"text": fact})
        check("재즈" in rb.text, f"H2 쓰기→읽기 왕복: bob이 자기 저장 사실 회상 (got {rb.text[:40]!r})")

        # 교차유저: alice 스코프 회상 → bob이 쓴 사실 없음.
        mr_alice = MemoryProvider(SessionLocal, alice_uid)
        ra = await mr_alice.invoke(_MemBacking("user"), {"text": fact})
        check("재즈" not in ra.text, "H2 교차유저: alice는 bob이 쓴 사실 회상 0(자기 스코프 쓰기)")
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
        print("      U·G가 핵심 불변식(self-scope 쓰기·승인 게이트 reject/approve) 보증.")


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS (VERIFY105_OK)")
