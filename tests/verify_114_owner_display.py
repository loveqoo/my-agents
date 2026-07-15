"""스펙 114 검증 — owner_id·can_manage 노출(UI 소유 표시 + 관리 게이팅 파생).

  [U] 단위 — may_manage(불리언 술어)가 assert_may_manage와 동치.
  [H] 통합(실 DB + ASGI) — list/get 응답에 owner_id·can_manage: superuser=전부 true,
      member=자기/특권만 true(NULL·타인=false).

실행: cd packages/api && uv run python ../../tests/verify_114_owner_display.py
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
    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.is_active = True
        self.is_verified = True
        self.email = f"u-{self.id.hex[:6]}@x"


def _as(p):
    app.dependency_overrides[current_principal] = lambda: p


def unit_checks() -> None:
    from fastapi import HTTPException
    from api.ownership import assert_may_manage, may_manage

    print("[U] may_manage ↔ assert_may_manage 동치")
    alice = Stub()
    for row_owner, principal, expect in [
        (str(alice.id), alice, True),            # 소유자 본인
        (str(uuid.uuid4()), alice, False),       # 타인
        (None, alice, False),                    # NULL-owned member
        (None, Stub(is_superuser=True), True),   # NULL-owned 특권
        (str(uuid.uuid4()), "machine", True),    # 머신 토큰 특권
    ]:
        b = may_manage(row_owner, principal, None)
        # assert 동치: b True면 예외 없음, False면 404
        raised = False
        class R: owner_id = row_owner
        try:
            assert_may_manage(R(), principal, None)
        except HTTPException:
            raised = True
        check(b == expect and (b != raised), f"U1 may_manage({row_owner and row_owner[:6]},{getattr(principal,'email',principal)})={b} 동치")


async def integration_checks() -> None:
    print("[H] 통합 — list/get owner_id·can_manage")
    from api.db import SessionLocal
    from api.models import Agent

    alice, bob, admin = Stub(), Stub(), Stub(is_superuser=True)
    t = httpx.ASGITransport(app=app)
    made = []
    try:
        async with httpx.AsyncClient(transport=t, base_url="http://t", timeout=60) as c:
            _as(alice)
            r = await c.post("/agents", json={"name": f"o114-{uuid.uuid4().hex[:6]}",
                             "config": {"model": "mock-llm", "prompt": "", "historyDepth": 6}})
            aid = r.json()["id"]; made.append(aid)
            check(r.json().get("owner_id") == str(alice.id), "H1 생성 응답 owner_id=alice")
            check(r.json().get("can_manage") is True, "H1 생성 응답 can_manage=True(행위자)")

            # NULL-owned 레거시 1개
            async with SessionLocal() as db:
                leg = Agent(agent_id=f"agt_o114_{uuid.uuid4().hex[:6]}", name="leg", source="ui",
                            model="mock-llm", prompt="", history_depth=6, config={"model": "mock-llm"},
                            exposed={"a2a": False}, status="idle", owner_id=None)
                db.add(leg); await db.commit(); made.append(str(leg.id))

            # alice 시점 목록: 자기 것 can_manage=true, NULL·타인=false
            _as(alice)
            lst = (await c.get("/agents")).json()
            mine = next(a for a in lst if a["id"] == aid)
            legrow = next(a for a in lst if a["owner_id"] is None)
            check(mine["can_manage"] is True, "H2 alice: 자기 에이전트 can_manage=True")
            check(legrow["can_manage"] is False, "H2 alice: NULL-owned can_manage=False")

            # bob 시점: alice 것 can_manage=false
            _as(bob)
            lst_b = (await c.get("/agents")).json()
            mine_b = next(a for a in lst_b if a["id"] == aid)
            check(mine_b["can_manage"] is False, "H3 bob: 타인(alice) 에이전트 can_manage=False")

            # superuser 시점: 전부 true
            _as(admin)
            lst_s = (await c.get("/agents")).json()
            check(all(a["can_manage"] for a in lst_s if a["id"] in (aid, str(made[1]))),
                  "H4 superuser: 전부 can_manage=True")
            # get 단건도 파생
            g = (await c.get(f"/agents/{aid}")).json()
            check(g["can_manage"] is True and g["owner_id"] == str(alice.id), "H4 GET 단건도 owner_id·can_manage")
    finally:
        _as(Stub(is_superuser=True))
        async with httpx.AsyncClient(transport=t, base_url="http://t", timeout=60) as c:
            for aid in made:
                await c.delete(f"/agents/{aid}")
        app.dependency_overrides.pop(current_principal, None)


async def main() -> None:
    unit_checks()
    print()
    try:
        await integration_checks()
    except Exception as exc:  # noqa: BLE001
        import traceback; traceback.print_exc()
        check(False, f"[H] 예외 {type(exc).__name__}: {exc}")
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
    print("✅ ALL PASS (VERIFY114_OK)")
