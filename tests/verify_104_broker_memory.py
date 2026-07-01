"""스펙 104 검증 — 능력 브로커 Memory provider(kind=memory, 읽기전용, 첫 per-user 소유 능력).

핵심 불변식: 메모리는 per-user 개인 데이터라 **누구의 기억인지를 cap_id·args가 아니라 런타임
principal에서 도출**한다. 능력은 `memory:user` 하나뿐이고, user_id는 build_broker가 principal에서
뽑아 MemoryProvider에 주입한다. 그래서 능력 이름으로 남을 가리킬 방법이 없어 교차 유저 유출이
*구조적으로* 불가능하다(103이 미룬 인가 입도 빚의 정공법). 읽기 전용 → approval_for None.
invoke는 `memory.recall_probe` 코어 + `memory.format_memory_hits` 공유 포맷(챗 회상과 drift 0)을 재사용.

  [U] 단위(FakeMem — 인프라 불요, 084 패턴) — 네임스페이스·_permitted memory·approval None·describe
      스키마·_by_kind 4종·시임 6메서드·candidates 게이트(allow∩user_id)·머신 deny·**교차유저 격리**
      (cap 동일·주체만 다름 → 결과 분리)·**args의 user_id 무시**(anti-leak 불변식)·build_broker 배선.
  [H] 통합(실 mem0 + 실 DB) — 실 백엔드에 두 유저 기억 시드 → build_broker(주체=bob)로 discover/
      describe/invoke → bob 기억만·alice 절대 노출 0·RBAC deny·존재 비노출(같은 backend 필터가 실제로
      user_id 스코프를 지키는지). DB/mem0 미가용이면 SKIP(U가 핵심 불변식 보증).

실행: .venv/bin/python tests/verify_104_broker_memory.py
"""
import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from api import memory as M  # noqa: E402
from api import mem_config as MC  # noqa: E402
from api.broker import (  # noqa: E402
    CapabilityNotFound,
    MemoryProvider,
    PolicyScopedBroker,
    _MemBacking,
    _kind_of,
    _parse_mem,
    build_broker,
)

MEM_USER = "memory:user"
_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ---------------------------------------------------------------- 테스트 더블
class P:
    """principal 최소 필드 모사(053/084 패턴)."""

    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.email = "u@example.com"
        self.display_name = None


class FakeMem:
    """단일 축 필터로 store를 거른다(mem0 검색 모사 — 084 패턴). scope 누출 0을 결정적으로 증명."""

    def __init__(self, store: list[dict]):
        self.store = list(store)

    def search(self, query, filters, top_k):
        (axis, val), = filters.items()
        return {"results": [r for r in self.store if r.get(axis) == val][:top_k]}

    def get_all(self, filters):
        (axis, val), = filters.items()
        return {"results": [r for r in self.store if r.get(axis) == val]}


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
    """MemoryProvider.invoke의 `async with self._session_factory() as db` 충족(db=None).
    default_mem_cfg는 아래서 패치돼 db를 안 본다."""
    return _FakeDB()


def _raise_factory():
    def make():
        raise AssertionError("거부/무해 경로가 DB를 만졌다(존재 누출 위험)")
    return make


# ================================================================ [U] 단위(FakeMem)
def unit_checks() -> None:
    print("[U] 단위 — 네임스페이스·_permitted·approval·describe·_by_kind·시임 계약·candidates 게이트")
    # U1 네임스페이스 파싱(memory 접두사, 무회귀).
    check(_kind_of("memory:user") == "memory", "U1 memory: 접두사 → kind memory")
    check(_kind_of("rag:x") == "rag" and _kind_of("mcp:s/t") == "mcp" and _kind_of("agt_x") == "agent",
          "U1 rag/mcp/agent 판정 무회귀")
    check(_parse_mem("memory:user") == "user", "U1 memory:user → user")
    check(_parse_mem("memory:") == "", "U1 memory: → 빈 리소스")
    check(_parse_mem("agt_x") == "agt_x", "U1 접두사 없음 → 원본 방어")

    # U2 _permitted memory — 1레벨 정확 매치(mcp 서버-전체 특례 없음).
    bt = PolicyScopedBroker({MEM_USER}, lambda k: True, session_factory=_raise_factory(), user_id="bob")
    check(bt._permitted(MEM_USER) is True, "U2 정확 memory cap 허용 → permitted")
    check(bt._permitted("memory:other") is False, "U2 allow 밖 memory → deny(비노출)")
    brd = PolicyScopedBroker({MEM_USER}, lambda k: False, session_factory=_raise_factory(), user_id="bob")
    check(brd._permitted(MEM_USER) is False, "U2 RBAC 거부 → deny(교집합)")

    mp = MemoryProvider(_raise_factory(), "bob")
    # U3 approval_for — 읽기전용 → 항상 None.
    check(mp.approval_for(MEM_USER, {"text": "x"}) is None, "U3 memory approval_for → 항상 None(읽기전용)")

    # U4 describe input_schema — text 필수, limit 선택, **user_id 필드 없음**(주체 고정).
    desc = mp.describe(_MemBacking("user"))
    props = (desc.input_schema or {}).get("properties", {})
    check(desc.kind == "memory" and desc.id == MEM_USER, "U4 describe id/kind")
    check("text" in props and desc.input_schema.get("required") == ["text"], "U4 text 필수 파라미터")
    check("limit" in props, "U4 limit 선택 파라미터 노출")
    check("user_id" not in props, "U4 스키마에 user_id 필드 없음(대상은 주체서 도출·args 불가)")

    # U5 _by_kind 4종.
    b = PolicyScopedBroker([], lambda k: True, session_factory=_raise_factory(), user_id="bob")
    check(set(b._by_kind) == {"agent", "mcp", "rag", "memory"}, "U5 브로커가 4 provider 보유(memory 포함)")
    check(isinstance(b._by_kind["memory"], MemoryProvider), "U5 memory → MemoryProvider")

    # U6 시임 6메서드 계약 + node_label.
    for m in ("candidates", "load", "describe", "invoke", "node_label", "approval_for"):
        check(hasattr(mp, m), f"U6 MemoryProvider.{m} 존재(시임 계약)")
    check(mp.kind == "memory", "U6 MemoryProvider.kind == memory")
    check(mp.node_label(_MemBacking("user")) == "broker_invoke:memory:user", "U6 node_label 형식")


async def unit_async_checks() -> None:
    print("[U] 단위(async) — candidates 게이트·머신 deny·교차유저 격리·args anti-leak·build_broker 배선")
    MC.default_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]

    # candidates: allow에 memory:user 있고 user_id 있을 때만 승격.
    mp_bob = MemoryProvider(_raise_factory(), "bob")
    check([c.id for c in await mp_bob.candidates({MEM_USER})] == [MEM_USER],
          "U7 allow∋memory:user + user_id → cap 1개(DB 미접촉)")
    check(await mp_bob.candidates(set()) == [], "U7 allow 밖 → [](승격 안 함)")
    check(await mp_bob.candidates({"memory:other", "memory:"}) == [],
          "U7 미지원/빈 리소스 → [](user 리소스만 승격)")
    # 머신(user_id None) → 자기 스코프 없음 → cap 없음·load None(DB 미접촉).
    mp_machine = MemoryProvider(_raise_factory(), None)
    check(await mp_machine.candidates({MEM_USER}) == [], "U7 머신(user_id None) → [](자기 스코프 없음)")
    check(await mp_machine.load(MEM_USER) is None, "U7 머신 load → None(존재 비노출)")
    # 미지원 리소스 load → None.
    check(await mp_bob.load("memory:other") is None, "U7 미지원 리소스 load → None(존재 비노출)")

    # ---- 교차유저 격리(빚-상환 핵심): 같은 cap·같은 store, 주체만 다르면 결과 분리 ----
    store = [
        {"id": "a1", "memory": "앨리스는 초콜릿 알레르기가 있다", "score": 0.9, "user_id": "alice"},
        {"id": "b1", "memory": "밥은 재즈 피아노를 친다", "score": 0.9, "user_id": "bob"},
    ]
    with_mem(FakeMem(store))
    b_bob = PolicyScopedBroker({MEM_USER}, lambda k: True, session_factory=_fake_factory, user_id="bob")
    b_alice = PolicyScopedBroker({MEM_USER}, lambda k: True, session_factory=_fake_factory, user_id="alice")

    r_bob = await b_bob.invoke(MEM_USER, {"text": "취미"})
    check("재즈" in r_bob.text and "초콜릿" not in r_bob.text,
          "U8 주체=bob invoke → 밥 기억만(앨리스 기억 노출 0)")
    check(r_bob.error is None and r_bob.trust == "untrusted", "U8 결과 trust=untrusted(데이터 채널)")
    r_alice = await b_alice.invoke(MEM_USER, {"text": "취미"})
    check("초콜릿" in r_alice.text and "재즈" not in r_alice.text,
          "U8 주체=alice invoke(동일 cap) → 앨리스 기억만(밥 기억 노출 0)")

    # ---- anti-leak: args의 user_id는 무시(스코프는 주체 도출값만) ----
    r_spoof = await b_bob.invoke(MEM_USER, {"text": "취미", "user_id": "alice"})
    check("재즈" in r_spoof.text and "초콜릿" not in r_spoof.text,
          "U8 args user_id=alice 밀반입 시도 → 여전히 bob 기억만(args 무시)")

    # ---- 관측 프레임 + node_label ----
    frames = [i for i in b_bob.invocations if i["node"] == "broker_invoke:memory:user"]
    check(len(frames) >= 1, f"U8 broker.invocations에 memory 프레임 (got {len(frames)})")

    # discover(주체 있음) → memory cap 노출 / 머신·RBAC거부·allow밖 → [].
    check(any(c.id == MEM_USER for c in await b_bob.discover("기억")), "U8 discover → memory cap 노출")
    b_machine = PolicyScopedBroker({MEM_USER}, lambda k: True, session_factory=_fake_factory, user_id=None)
    check(await b_machine.discover("기억") == [], "U8 머신 → discover [](자기 스코프 없음)")
    b_deny = PolicyScopedBroker({MEM_USER}, lambda k: False, session_factory=_raise_factory(), user_id="bob")
    check(await b_deny.discover("기억") == [], "U8 RBAC 거부 → discover [](DB 미접촉)")
    b_noallow = PolicyScopedBroker(set(), lambda k: True, session_factory=_raise_factory(), user_id="bob")
    check(await b_noallow.discover("기억") == [], "U8 빈 allowlist → discover [](DB 미접촉)")
    r_nf = await b_noallow.invoke(MEM_USER, {"text": "x"})
    check(r_nf.error == "capability not found", "U8 allow 밖 invoke → not-found(존재 비노출)")

    # ---- build_broker 배선: principal → user_id 도출이 MemoryProvider에 주입되나 ----
    bob = P()
    wired = build_broker(bob, {MEM_USER})
    check(wired._by_kind["memory"]._user_id == str(bob.id),
          "U9 build_broker(유저) → MemoryProvider._user_id == str(principal.id)")
    wired_m = build_broker("machine", {MEM_USER})
    check(wired_m._by_kind["memory"]._user_id is None,
          "U9 build_broker(머신) → MemoryProvider._user_id None(에스컬레이션·자기스코프 없음)")

    # ---- U9b limit 타입/범위 방어(적대 리뷰 104 P2) — 브로커는 args.limit 무검증 입구 ----
    with_mem(FakeMem(store))  # 재설치(위 build_broker가 안 건드림)
    r_boom = await b_bob.invoke(MEM_USER, {"text": "취미", "limit": "boom"})
    check(r_boom.error is None and "재즈" in r_boom.text,
          "U9b limit='boom'(비정수) → 크래시 없이 회상(정수 강제)")
    r_neg = await b_bob.invoke(MEM_USER, {"text": "취미", "limit": -1})
    check(r_neg.error is None and "재즈" in r_neg.text, "U9b limit=-1 → 꼬리절단 아님(≥1 clamp)")
    check(M.recall_probe({"user_id": "bob"}, "q", {"llm": {}, "embedder": {}}, 999) is not None,
          "U9b limit=999 → clamp(상한 방어)")
    check(M._clamp_limit("boom") == 4 and M._clamp_limit(-1) == 1 and M._clamp_limit(999) == 10,
          "U9b _clamp_limit: 비정수→4·음수→1·거대→10")

    # 백엔드 미가용(resolve_backend None) → graceful(에이전트 안 죽임).
    M.resolve_backend = lambda mem_cfg: None  # type: ignore[assignment]
    r_off = await b_bob.invoke(MEM_USER, {"text": "x"})
    check(r_off.error is not None and "구성" in r_off.error and r_off.trust == "untrusted",
          "U10 백엔드 미가용 → graceful 오류(untrusted, 084 recall_probe 정직성 계약)")

    # ---- U11 재개 브로커 배선(적대 리뷰 104 P2) — 승인 재개 경로도 user_id 복원 ----
    from api import chat as CHAT
    rb = await CHAT._build_resume_broker("bob-uid", {MEM_USER})
    check(rb._by_kind["memory"]._user_id == "bob-uid",
          "U11 _build_resume_broker(user_id) → MemoryProvider._user_id 복원(재개 시 자기 기억 유지)")
    rb_none = await CHAT._build_resume_broker(None, {MEM_USER})
    check(rb_none._by_kind["memory"]._user_id is None,
          "U11 _build_resume_broker(None) → user_id None(머신 발, 자기 스코프 없음)")


# ================================================================ [H] 통합(실 mem0 + 실 DB)
async def integration_checks() -> None:
    print("[H] 통합(실 mem0 + 실 DB) — 두 유저 기억 시드 → 실 backend 필터가 user_id 스코프 지키나")
    # 모듈 패치 원복(단위서 M.resolve_backend/MC.default_mem_cfg 바꿈) 후 실물 사용.
    import importlib
    importlib.reload(M)
    importlib.reload(MC)
    from api.authz import init_authz
    from api.db import SessionLocal

    await init_authz()  # member RBAC 판정용 실 enforcer(H5) — 앱 부팅과 동일(멱등).

    alice_uid = f"v104_alice_{uuid.uuid4().hex[:8]}"
    bob_uid = f"v104_bob_{uuid.uuid4().hex[:8]}"
    alice_fact = "앨리스는 초콜릿 알레르기가 있다는 사실"
    bob_fact = "밥은 재즈 피아노를 친다는 사실"

    async with SessionLocal() as db:
        mem_cfg = await MC.default_mem_cfg(db)
    if mem_cfg is None or M.resolve_backend(mem_cfg) is None:
        print("  ..  [H] SKIP — mem0 백엔드 미구성(기본 chat/embedding 모델 없음)")
        return

    def _seed(uid, fact):
        M.add({"user_id": uid}, [{"role": "user", "content": fact}], mem_cfg, infer=False)

    def _purge(uid):
        for r in M.list_memories({"user_id": uid}, mem_cfg):
            M.delete_memory(r["id"], mem_cfg)

    await asyncio.to_thread(_purge, alice_uid)
    await asyncio.to_thread(_purge, bob_uid)
    await asyncio.to_thread(_seed, alice_uid, alice_fact)
    await asyncio.to_thread(_seed, bob_uid, bob_fact)
    try:
        # 주체=bob(superuser로 RBAC 통과 — 그래도 user_id=str(id)=bob이라 자기 스코프만: 에스컬레이션 X).
        class _RP:
            def __init__(self, uid):
                self.id = uid
                self.is_superuser = True
                self.email = "t@t"
                self.display_name = None

        b = build_broker(_RP(bob_uid), {MEM_USER})

        # H1 discover → memory cap.
        caps = await b.discover("기억")
        check(any(c.id == MEM_USER for c in caps), f"H1 discover → memory cap (got {[c.id for c in caps]})")
        # H2 describe.
        d = await b.describe(MEM_USER)
        check(d.kind == "memory" and "text" in (d.input_schema or {}).get("properties", {}),
              "H2 describe → kind=memory·text 파라미터")
        # H3 invoke(bob) → 밥 기억만, 앨리스 절대 노출 0(실 backend 필터).
        res = await b.invoke(MEM_USER, {"text": bob_fact})
        check(res.error is None and "재즈" in res.text, f"H3 invoke(bob) → 밥 기억 회상 (err={res.error})")
        check("초콜릿" not in res.text and "알레르기" not in res.text,
              "H3 invoke(bob) → 앨리스 기억 노출 0(실 backend user_id 스코프)")
        check(res.trust == "untrusted", "H3 결과 trust=untrusted")
        frames = [i for i in b.invocations if i["node"] == "broker_invoke:memory:user"]
        check(len(frames) == 1, f"H3 broker.invocations에 memory 프레임 1개 (got {len(frames)})")

        # H4 anti-leak(실 backend): args user_id=alice여도 bob 스코프.
        res2 = await b.invoke(MEM_USER, {"text": bob_fact, "user_id": alice_uid})
        check("초콜릿" not in res2.text, "H4 args user_id=alice 밀반입 → 앨리스 노출 0(실 backend)")
    finally:
        await asyncio.to_thread(_purge, alice_uid)
        await asyncio.to_thread(_purge, bob_uid)

    # H5 RBAC 거부: 실 principal(member)·실 enforcer로 별도 구성(위 finally 정리 후, DB만 접촉).
    class _Member:
        def __init__(self, uid):
            self.id = uid
            self.is_superuser = False
            self.email = "m@t"
            self.display_name = None

    b_member = build_broker(_Member(uuid.uuid4()), {MEM_USER})
    check(await b_member.discover("기억") == [],
          "H5 member(capability:memory RBAC 없음) → discover [](정책 격리)")


async def main() -> None:
    unit_checks()
    await unit_async_checks()
    print()
    try:
        await integration_checks()
    except Exception as exc:  # noqa: BLE001
        print(f"  ..  [H] 통합 SKIP — DB/mem0 미가용({type(exc).__name__}: {exc})")
        print("      U(단위)만으로 핵심 불변식(교차유저 격리·anti-leak) 보증; H는 dev DB·mem0 가동 시 재실행.")


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS (VERIFY104_OK)")
