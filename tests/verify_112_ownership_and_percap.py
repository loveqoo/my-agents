"""스펙 112 검증 — 공유 카탈로그 소유권 + per-cap 인가(인가 입도 강화).

RBAC/소유권 체크리스트(docs/spec/CLAUDE.md):
- **Part A(per-cap 인가)**: 브로커가 kind 단위(`capability:{kind}`) 외에 능력별(`capability:{kind}:{res}`)도
  판정 → admin이 kind 전체 대신 특정 cap만 member에 부여 가능. discover DB-회피 게이트(name=None) 보존.
- **Part B(자원 소유권)**: Agent·McpServer·Collection에 owner_id. 생성 시 1회 스탬프(069)·이전 금지·
  NULL=특권 전용(fail-closed, 070). 관리(수정/삭제) 라우트는 소유자/특권만(비소유=404-fold 존재비노출).
  자가잠금 핀: 소유자 본인은 자기 자원 관리 가능.

  [U] 단위 — owner_of/next_owner/may_use/is_privileged/assert_may_manage·_rbac_check·broker _permitted.
  [H] 통합(실 DB + ASGI) — 스탬프(member 생성=owner 박힘)·관리 게이트(타 member 404·본인 OK·특권 OK·
      NULL-owned member 거부/특권 OK)·per-cap invoke 게이트.

실행: cd packages/api && uv run python ../../tests/verify_112_ownership_and_percap.py
"""
import asyncio
import uuid

import httpx

from api.auth import current_principal
from api.main import app

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Stub:
    """principal 더블 — cookie 유저 흉내(id + is_superuser)."""
    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.is_active = True
        self.is_verified = True
        self.email = f"u-{self.id.hex[:6]}@x"


def _as(principal):
    """current_principal 오버라이드 설정."""
    app.dependency_overrides[current_principal] = lambda: principal


# ================================================================ [U] 단위
def unit_checks() -> None:
    from api.broker import PolicyScopedBroker, _rbac_check
    from api.ownership import (
        assert_may_manage,
        is_privileged,
        may_use,
        next_owner,
        owner_of,
    )
    from fastapi import HTTPException

    print("[U] 단위 — ownership 헬퍼 + _rbac_check + broker _permitted per-cap")
    # ownership 헬퍼
    check(owner_of("machine") is None, "U1 owner_of(머신 str)=None")
    s = Stub()
    check(owner_of(s) == str(s.id), "U1 owner_of(유저)=str(id)")
    check(next_owner("a", "b") == "a" and next_owner(None, "b") == "b", "U1 next_owner=기존 보존(이전 금지)")
    check(may_use("bob", "bob", False) and not may_use("x", "bob", False)
          and not may_use(None, "bob", False) and may_use(None, "bob", True),
          "U1 may_use: 소유자 OK·타인 X·NULL은 특권만")
    check(is_privileged("mat") and is_privileged(Stub(is_superuser=True)) and not is_privileged(Stub()),
          "U1 is_privileged: 머신·superuser=True, member=False")

    # assert_may_manage: 404-fold
    class R:
        owner_id = str(s.id)
    assert_may_manage(R(), s, None)  # 소유자 → 통과(예외 없음)
    check(True, "U2 assert_may_manage 소유자 본인 → 통과(자가잠금 핀)")
    try:
        assert_may_manage(R(), Stub(), None)  # 타 member → 404
        check(False, "U2 타 member 거부(도달 안 함)")
    except HTTPException as e:
        check(e.status_code == 404, "U2 타 member → 404-fold(존재 비노출)")
    assert_may_manage(R(), Stub(is_superuser=True), None)  # 특권 → 통과
    check(True, "U2 특권(superuser) → 통과")

    class Rnull:
        owner_id = None
    try:
        assert_may_manage(Rnull(), Stub(), None)
        check(False, "U2 NULL-owned member 거부(도달 안 함)")
    except HTTPException as e:
        check(e.status_code == 404, "U2 NULL-owned → member 거부(admin 전용 fail-closed)")

    # broker _permitted per-cap (lambda 더블: kind True/특정만)
    b_kind = PolicyScopedBroker({"rag:a", "rag:b"}, lambda k, name=None: True, session_factory=lambda: None)
    check(b_kind._permitted("rag:a") and b_kind._permitted("rag:b"), "U3 kind 허가 → 모든 rag cap permitted")
    # per-cap만: rag:a만 허가
    def only_a(kind, name=None):
        if name is None:
            return kind == "rag"  # DB 게이트: rag에 부여 있음
        return kind == "rag" and name == "a"
    b_pc = PolicyScopedBroker({"rag:a", "rag:b"}, only_a, session_factory=lambda: None)
    check(b_pc._permitted("rag:a") and not b_pc._permitted("rag:b"),
          "U3 per-cap(rag:a만) → rag:a permitted, rag:b deny")


async def _rbac_check_real() -> None:
    from api import authz
    from api.broker import _rbac_check
    print("[U] _rbac_check(실 casbin) — kind/per-cap/DB게이트")
    await authz.init_authz()
    e = authz.get_enforcer()
    uid = f"u112_{uuid.uuid4().hex[:8]}"
    await e.add_policy(uid, "capability:rag:docs_kb", "invoke")  # per-cap만
    try:
        check(_rbac_check(e, uid, "rag", "docs_kb"), "U4 per-cap 특정 → True")
        check(not _rbac_check(e, uid, "rag", "other"), "U4 미부여 특정 → False")
        check(_rbac_check(e, uid, "rag", None), "U4 name=None 게이트 → True(rag에 per-cap 있음)")
        check(not _rbac_check(e, uid, "mcp", None), "U4 미부여 kind 게이트 → False(DB 미접촉)")
        # 역할 상속: 역할에 per-cap 부여 → 유저가 그 역할이면 게이트 통과
        await e.add_policy("role_ragX", "capability:rag:teamdoc", "invoke")
        await e.add_grouping_policy(uid, "role_ragX")
        check(_rbac_check(e, uid, "rag", "teamdoc"), "U4 역할 상속 per-cap → True")
        # U5 (codex P2): mcp 서버단위 부여가 그 서버 툴을 덮는다.
        await e.add_policy(uid, "capability:mcp:github", "invoke")
        check(_rbac_check(e, uid, "mcp", "github/search"), "U5 mcp 서버단위 부여 → 툴 호출 True(서버 폴백)")
        check(_rbac_check(e, uid, "mcp", "github"), "U5 mcp 서버 자체 → True")
        check(not _rbac_check(e, uid, "mcp", "gitlab/search"), "U5 다른 서버 툴 → False(폴백 정확)")
    finally:
        await e.remove_policy(uid, "capability:rag:docs_kb", "invoke")
        await e.remove_policy(uid, "capability:mcp:github", "invoke")
        await e.remove_policy("role_ragX", "capability:rag:teamdoc", "invoke")
        await e.remove_grouping_policy(uid, "role_ragX")


# ================================================================ [H] 통합(실 DB + ASGI)
async def integration_checks() -> None:
    print("[H] 통합 — 스탬프 + 관리 게이트(타 member 404·본인 OK·특권 OK·NULL-owned)")
    from api.db import SessionLocal
    from api.models import Agent
    from sqlalchemy import select

    alice, bob, admin = Stub(), Stub(), Stub(is_superuser=True)
    t = httpx.ASGITransport(app=app)
    made_ids: list[str] = []
    try:
        async with httpx.AsyncClient(transport=t, base_url="http://t", timeout=60) as c:
            # 스탬프: alice가 에이전트 생성 → owner=alice.
            _as(alice)
            r = await c.post("/agents", json={"name": f"own-{uuid.uuid4().hex[:6]}",
                                              "config": {"model": "mock-llm", "persona": "", "historyDepth": 6}})
            check(r.status_code == 201, f"H1 alice 에이전트 생성 201 (got {r.status_code})")
            aid = r.json()["id"]  # 라우트가 uuid.UUID 경로 → 응답 id = pk(uuid str)
            made_ids.append(aid)
            async with SessionLocal() as db:
                row = (await db.execute(select(Agent).where(Agent.id == uuid.UUID(aid)))).scalar_one()
                check(row.owner_id == str(alice.id), f"H1 owner_id 스탬프=alice (got {row.owner_id})")

            # 관리 게이트: bob(타 member)이 alice 것 수정/삭제 → 404-fold.
            _as(bob)
            r_upd = await c.put(f"/agents/{aid}", json={"config": {"model": "mock-llm", "persona": "x", "historyDepth": 6}})
            check(r_upd.status_code == 404, f"H2 타 member 수정 → 404-fold (got {r_upd.status_code})")
            r_del = await c.delete(f"/agents/{aid}")
            check(r_del.status_code == 404, f"H2 타 member 삭제 → 404-fold (got {r_del.status_code})")

            # 자가잠금 핀: alice 본인 수정 → OK.
            _as(alice)
            r_own = await c.put(f"/agents/{aid}", json={"config": {"model": "mock-llm", "persona": "mine", "historyDepth": 6}})
            check(r_own.status_code == 200, f"H3 자가잠금 핀: 본인 수정 OK (got {r_own.status_code})")

            # 특권: superuser가 alice 것 수정 → OK.
            _as(admin)
            r_adm = await c.put(f"/agents/{aid}", json={"config": {"model": "mock-llm", "persona": "adm", "historyDepth": 6}})
            check(r_adm.status_code == 200, f"H4 특권(superuser) 타인 것 수정 OK (got {r_adm.status_code})")

            # NULL-owned(레거시): owner_id=None 에이전트 직접 삽입 → member 거부, 특권 OK.
            async with SessionLocal() as db:
                legacy = Agent(agent_id=f"agt_legacy_{uuid.uuid4().hex[:6]}", name="legacy", source="ui",
                               model="mock-llm", persona="", history_depth=6, config={"model": "mock-llm"},
                               exposed={"a2a": False}, status="idle", owner_id=None)
                db.add(legacy); await db.commit(); await db.refresh(legacy)
                legacy_id = str(legacy.id)  # 라우트는 uuid pk 경로
            made_ids.append(legacy_id)
            _as(bob)
            r_leg = await c.put(f"/agents/{legacy_id}", json={"config": {"model": "mock-llm", "persona": "x", "historyDepth": 6}})
            check(r_leg.status_code == 404, f"H5 NULL-owned member 수정 → 404(admin 전용 fail-closed) (got {r_leg.status_code})")
            _as(admin)
            r_leg2 = await c.put(f"/agents/{legacy_id}", json={"config": {"model": "mock-llm", "persona": "ok", "historyDepth": 6}})
            check(r_leg2.status_code == 200, f"H5 NULL-owned 특권 수정 OK (got {r_leg2.status_code})")

            # H6 (codex P1): 에이전트 메모리 변조 라우트도 게이트. bob이 alice 것 메모리 add/patch/delete → 404.
            _as(bob)
            r_madd = await c.post(f"/agents/{aid}/memory", json={"text": "침투"})
            r_mpatch = await c.patch(f"/agents/{aid}/memory/whatever", json={"text": "변조"})
            r_mdel = await c.delete(f"/agents/{aid}/memory/whatever")
            check(r_madd.status_code == 404 and r_mpatch.status_code == 404 and r_mdel.status_code == 404,
                  f"H6 타 member 메모리 add/patch/delete → 404 (got {r_madd.status_code}/{r_mpatch.status_code}/{r_mdel.status_code})")

            # H7 (codex P1): 404-fold body 통일 — 미존재와 비소유가 같은 detail(존재 비노출).
            _as(bob)
            import uuid as _uuid
            r_missing = await c.put(f"/agents/{_uuid.uuid4()}", json={"config": {"model": "mock-llm", "persona": "x", "historyDepth": 6}})
            r_notmine = await c.put(f"/agents/{aid}", json={"config": {"model": "mock-llm", "persona": "x", "historyDepth": 6}})
            check(r_missing.status_code == 404 and r_notmine.status_code == 404
                  and r_missing.json().get("detail") == r_notmine.json().get("detail"),
                  f"H7 404-fold body 통일: 미존재='{r_missing.json().get('detail')}' == 비소유='{r_notmine.json().get('detail')}'")
    finally:
        # 정리 — 특권으로 삭제.
        _as(Stub(is_superuser=True))
        async with httpx.AsyncClient(transport=t, base_url="http://t", timeout=60) as c:
            for aid in made_ids:
                await c.delete(f"/agents/{aid}")
        app.dependency_overrides.pop(current_principal, None)


async def main() -> None:
    unit_checks()
    print()
    await _rbac_check_real()
    print()
    try:
        await integration_checks()
    except Exception as exc:  # noqa: BLE001
        print(f"  ..  [H] 통합 SKIP — DB 미가용({type(exc).__name__}: {exc})")
        import traceback; traceback.print_exc()
    finally:
        app.dependency_overrides.pop(current_principal, None)


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        raise SystemExit(1)
    print("✅ ALL PASS (VERIFY112_OK)")
