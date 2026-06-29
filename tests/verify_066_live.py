"""스펙 066 검증(라이브 통합) — 승인 resolve 인가 3-way + list 스코핑을 실 HTTP 위에서.

verify_066_resolve_authz.py(단위)가 분기 로직을 격리 증명한다면, 여기선 **글루**를 증명한다:
실 쿠키 principal 해석(member/super), 머신 Bearer, DB list 스코핑 질의가 실제로 필터하는지,
그리고 enforce()가 정말 *소비*되는지(owner여도 정책 없으면 403 = fail-closed). 단위가 못 잡는
요청-경계·시드-글루를 잡는 rung(verification-ladder 3 rungs).

owner+self_approve **허용(200)** 경로는 라이브 enforcer에 self_approve 정책이 있어야 하는데,
별 프로세스라 정책 주입엔 서버 재기동이 필요하다 → 그 200 분기는 단위 rung이 권위 있게 덮고,
여기선 **기본 fail-closed**(member가 자기 data.read도 403)로 enforce가 게이트에 *실제 배선*됨을
증명한다(게이트가 perm을 무시했다면 owner는 200이었을 것). 민감도 구분의 라이브 양성(200) 증명은
seed+restart 절차로 별도 수행(스펙 066 검증 노트).

전제: API(127.0.0.1:8000)+실 DB가 떠 있어야 한다. 던짐용 계정(probe…@example.com)을 즉석
생성/삭제하고 합성 Approval 행을 직접 넣고 지운다(실 데이터 무오염).

실행: .venv/bin/python tests/verify_066_live.py  (API 서버 떠 있어야 함)
"""
import asyncio
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api.db import SessionLocal  # noqa: E402
from api.models import Approval, User  # noqa: E402

BASE = "http://127.0.0.1:8000"
MACHINE = (os.environ.get("API_AUTH_TOKEN") or "").strip()
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")

MEMBER_EMAIL = "probe066m@example.com"
SUPER_EMAIL = "probe066s@example.com"
PW = "Probe066-pw!"
PREFIX = "apr-066t-"

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _provision(create: bool) -> None:
    cmd = "create" if create else "delete"
    for email, extra in [(MEMBER_EMAIL, ["member"]), (SUPER_EMAIL, [])]:
        args = [PY, PROV, cmd, email] + ([PW] + extra if create else [])
        subprocess.run(args, check=False, capture_output=True, text=True)


async def _uid(session, email: str) -> str:
    return str((await session.execute(select(User.id).where(User.email == email))).scalar_one())


async def _insert_approvals(member_id: str, super_id: str) -> dict:
    """합성 pending Approval 4종 삽입. checkpoint/agent_pk 없음 → resume은 무해 no-op(가드)."""
    rows = {
        "own_delete": (member_id, "data.delete"),
        "own_read": (member_id, "data.read"),
        "others": (super_id, "data.read"),
        "null_owner": (None, "data.read"),
    }
    ids = {}
    async with SessionLocal() as s:
        for i, (k, (uid, perm)) in enumerate(rows.items()):
            apid = f"{PREFIX}{i}"
            ids[k] = apid
            s.add(Approval(
                approval_id=apid, session_id="sess-066t", user_id=uid,
                agent_pk=None, agent_name="probe066", permission=perm,
                action=f"{perm}.action", args={}, summary="probe066", checkpoint=None,
                status="pending",
            ))
        await s.commit()
    return ids


async def _cleanup_db() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(Approval).where(Approval.approval_id.like(f"{PREFIX}%")))
        await s.commit()


async def _login(client: httpx.AsyncClient, email: str) -> bool:
    r = await client.post("/auth/login", data={"username": email, "password": PW},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.status_code in (200, 204)


def _ids_in(items, want: set[str]) -> set[str]:
    got = {it["id"] for it in items if it["id"].startswith(PREFIX)}
    return got & want


async def main() -> None:
    if not MACHINE:
        print("❌ 전제 실패 — API_AUTH_TOKEN 미설정(.env). 종료.")
        sys.exit(1)
    # 머신 토큰으로 서버 생존 + 인증 확인.
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as mc:
        mc.headers["Authorization"] = f"Bearer {MACHINE}"
        pre = await mc.get("/approvals")
        check(pre.status_code == 200, f"PRE: 머신 토큰 GET /approvals 200 (서버 생존) — got {pre.status_code}")
        if pre.status_code != 200:
            print("❌ 전제 실패 — 서버/토큰. 종료."); sys.exit(1)

    _provision(create=True)
    try:
        async with SessionLocal() as s:
            member_id = await _uid(s, MEMBER_EMAIL)
            super_id = await _uid(s, SUPER_EMAIL)
        ids = await _insert_approvals(member_id, super_id)
        allids = set(ids.values())

        member = httpx.AsyncClient(base_url=BASE, timeout=10)
        superc = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine.headers["Authorization"] = f"Bearer {MACHINE}"
        try:
            check(await _login(member, MEMBER_EMAIL), "SETUP: member 로그인(쿠키)")
            check(await _login(superc, SUPER_EMAIL), "SETUP: super 로그인(쿠키)")

            # ---- L1 list 스코핑: member는 자기 것(own_*)만, 타인·NULL-owner 숨김 ----
            mlist = (await member.get("/approvals", params={"status": "pending"})).json()
            seen = _ids_in(mlist, allids)
            check(
                seen == {ids["own_delete"], ids["own_read"]},
                f"L1: member list = 자기 것만(own_delete·own_read) — got {sorted(seen)}",
            )
            check(ids["others"] not in seen, "L1: member에게 타인 소유 행 숨김(스코핑)")
            check(ids["null_owner"] not in seen, "L1: member에게 NULL-owner 행 숨김")

            # ---- L2/L3 admin/machine은 전체(4종 모두) ----
            slist = (await superc.get("/approvals", params={"status": "pending"})).json()
            check(_ids_in(slist, allids) == allids, "L2: super(admin) list = 전체 4종")
            mclist = (await machine.get("/approvals", params={"status": "pending"})).json()
            check(_ids_in(mclist, allids) == allids, "L3: 머신 list = 전체 4종")

            # ---- L4 resolve 인가(member 쿠키): 전부 거부(기본 fail-closed) ----
            async def mresolve(apid):
                return (await member.post(f"/approvals/{apid}/resolve", json={"decision": "approve"})).status_code

            # 비가시 행(타인·NULL-owner)은 404로 통일 — 존재 은폐(열거 오라클 차단, 적대리뷰 Low#1).
            check(await mresolve(ids["others"]) == 404, "L4(T1): member가 타인 행 resolve → 404(존재 은폐)")
            check(await mresolve(ids["null_owner"]) == 404, "L4(T2): member가 NULL-owner 행 resolve → 404(존재 은폐)")
            # 자기 행이지만 민감 perm → 403(목록에 보여 존재는 이미 알려짐, 권한만 부족).
            check(await mresolve(ids["own_delete"]) == 403, "L4: member가 자기 민감 perm(data.delete) → 403")
            check(
                await mresolve(ids["own_read"]) == 403,
                "L4(핵심): member가 자기 data.read도 → 403 (정책 부재=enforce 실제 소비, fail-closed)",
            )
            check(await mresolve("apr-066t-nope") == 404, "L4: 없는 approval_id → 404")

            # ---- L5 super(admin)는 민감 perm여도 승인(200) ----
            sd = (await superc.post(f"/approvals/{ids['own_delete']}/resolve", json={"decision": "approve"})).status_code
            check(sd == 200, f"L5: super가 민감 perm(data.delete) resolve → 200(admin 우선) — got {sd}")

            # ---- L6 머신 토큰 전체 승인(200) ----
            mc6 = (await machine.post(f"/approvals/{ids['own_read']}/resolve", json={"decision": "approve"})).status_code
            check(mc6 == 200, f"L6: 머신 토큰 resolve → 200(전체) — got {mc6}")
        finally:
            await member.aclose(); await superc.aclose(); await machine.aclose()
    finally:
        await _cleanup_db()
        _provision(create=False)

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 066 라이브 통합 — resolve 인가 글루·list 스코핑·fail-closed 전부 통과")


asyncio.run(main())
