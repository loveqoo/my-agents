"""스펙 067 검증(라이브 통합) — 세션 유저 스코핑을 실 HTTP 위에서.

verify_067_scope.py(단위)가 분기 로직을 격리 증명한다면, 여기선 **글루**를 증명한다:
실 쿠키 principal 해석(member/super), 머신 Bearer, DB 스코핑 질의가 실제로 필터하는지,
list↔item↔배지 세 입구가 일관되게 막히는지(404 존재 은폐).

전제: API(127.0.0.1:8000)+실 DB 생존. 던짐용 계정(probe…@example.com)·합성 Agent/Session/Message를
즉석 생성/삭제(실 데이터 무오염). member/super/머신 × own/타인/NULL-owner 세션.

실행: .venv/bin/python tests/verify_067_live.py  (API 서버 떠 있어야 함)
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
from api.models import Agent, Message, Session, User  # noqa: E402

BASE = "http://127.0.0.1:8000"
MACHINE = (os.environ.get("API_AUTH_TOKEN") or "").strip()
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")

MEMBER_EMAIL = "probe067m@example.com"
SUPER_EMAIL = "probe067s@example.com"
PW = "Probe067-pw!"
AGENT_ID = "agt-067t"
SPREFIX = "sess-067t-"

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


async def _seed(member_id: str, super_id: str) -> dict:
    """합성 Agent 1 + Session 3종(own·타인·NULL) + 각 user 메시지 1건."""
    ids = {}
    async with SessionLocal() as s:
        agent = Agent(agent_id=AGENT_ID, name="probe067", source="ui")
        s.add(agent)
        await s.flush()  # agent.id 확보
        rows = {"own": member_id, "others": super_id, "null_owner": None}
        for k, owner in rows.items():
            sid = f"{SPREFIX}{k}"
            ids[k] = sid
            sess = Session(session_id=sid, agent_pk=agent.id, agent_name="probe067",
                           user_id=owner, status="active")
            s.add(sess)
            await s.flush()
            s.add(Message(session_pk=sess.id, role="user", content=f"비밀-{k}"))
        await s.commit()
    return ids


async def _cleanup() -> None:
    async with SessionLocal() as s:
        # Session·Message는 agent CASCADE로 정리되지만 명시 삭제(독립).
        await s.execute(delete(Session).where(Session.session_id.like(f"{SPREFIX}%")))
        await s.execute(delete(Agent).where(Agent.agent_id == AGENT_ID))
        await s.commit()


async def _login(client: httpx.AsyncClient, email: str) -> bool:
    r = await client.post("/auth/login", data={"username": email, "password": PW},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.status_code in (200, 204)


def _our_ids(items, want: set[str]) -> set[str]:
    return {it["id"] for it in items if it["id"].startswith(SPREFIX)} & want


async def main() -> None:
    if not MACHINE:
        print("❌ 전제 실패 — API_AUTH_TOKEN 미설정(.env). 종료.")
        sys.exit(1)
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as mc:
        mc.headers["Authorization"] = f"Bearer {MACHINE}"
        pre = await mc.get("/sessions", params={"limit": 1})
        check(pre.status_code == 200, f"PRE: 머신 GET /sessions 200(서버 생존) — got {pre.status_code}")
        if pre.status_code != 200:
            print("❌ 전제 실패 — 서버/토큰. 종료."); sys.exit(1)

    _provision(create=True)
    try:
        async with SessionLocal() as s:
            member_id = await _uid(s, MEMBER_EMAIL)
            super_id = await _uid(s, SUPER_EMAIL)
        ids = await _seed(member_id, super_id)
        allids = set(ids.values())

        member = httpx.AsyncClient(base_url=BASE, timeout=10)
        superc = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine.headers["Authorization"] = f"Bearer {MACHINE}"
        try:
            check(await _login(member, MEMBER_EMAIL), "SETUP: member 로그인(쿠키)")
            check(await _login(superc, SUPER_EMAIL), "SETUP: super 로그인(쿠키)")

            # ---- D2 list 스코핑 ----
            mlist = (await member.get("/sessions", params={"limit": 100})).json()
            mseen = _our_ids(mlist["items"], allids)
            check(mseen == {ids["own"]}, f"D2: member list = 자기 세션만(own) — got {sorted(mseen)}")
            check(ids["others"] not in mseen, "D2(T1): member에게 타인 세션 숨김")
            check(ids["null_owner"] not in mseen, "D2(T3): member에게 NULL-owner 세션 숨김")

            slist = (await superc.get("/sessions", params={"limit": 100})).json()
            check(_our_ids(slist["items"], allids) == allids, "D2: super(admin) list = 전체 3종")
            mclist = (await machine.get("/sessions", params={"limit": 100})).json()
            check(_our_ids(mclist["items"], allids) == allids, "D2: 머신 list = 전체 3종")

            # ---- D4 item 가시성 404 (detail·messages·end) ----
            async def code(client, path, method="GET"):
                r = await (client.post(path) if method == "POST" else client.get(path))
                return r.status_code

            # member: 자기 것 200, 타인/NULL → 404(존재 은폐), 추측 → 404
            check(await code(member, f"/sessions/{ids['own']}") == 200, "D4: member 자기 세션 detail → 200")
            check(await code(member, f"/sessions/{ids['own']}/messages") == 200, "D4: member 자기 messages → 200")
            check(await code(member, f"/sessions/{ids['others']}") == 404, "D4(T2): member 타인 detail → 404(은폐)")
            check(await code(member, f"/sessions/{ids['others']}/messages") == 404, "D4(T2): member 타인 전사 → 404(은폐)")
            check(await code(member, f"/sessions/{ids['null_owner']}/messages") == 404, "D4(T3): member NULL-owner 전사 → 404")
            check(await code(member, f"/sessions/{SPREFIX}nope") == 404, "D4: member 없는 세션 → 404(부재와 동일)")

            # member 타인 세션 종료 변조 → 404 (그리고 실제로 status 안 바뀜)
            check(await code(member, f"/sessions/{ids['others']}/end", "POST") == 404, "D4(T5): member 타인 세션 end → 404")
            async with SessionLocal() as s:
                still = (await s.execute(select(Session.status).where(Session.session_id == ids["others"]))).scalar_one()
            check(still == "active", "D4(T5): 타인 세션 status 무변경(종료 변조 차단 실측)")

            # super: 타인(=member 소유) 세션도 200
            check(await code(superc, f"/sessions/{ids['own']}/messages") == 200, "D4: super 임의 세션 전사 → 200(전체)")
            check(await code(machine, f"/sessions/{ids['null_owner']}/messages") == 200, "D4: 머신 NULL-owner 전사 → 200(전체)")

            # ---- D3 배지 counts 스코핑 ----
            mcounts = mlist["counts"]
            scounts = slist["counts"]
            check(mcounts["all"] == 1, f"D3(T6): member 배지 all=1(자기 세션 수) — got {mcounts['all']}")
            check(scounts["all"] >= 3, f"D3: super 배지 all≥3(전역) — got {scounts['all']}")
            check(mcounts["all"] < scounts["all"], "D3(T6): member 배지 < super 배지(전역 누설 차단)")

            # ---- D5 list_user_ids 스코핑 ----
            muids = (await member.get("/sessions/users")).json()
            check(muids == [member_id], f"D5: member /sessions/users = 본인만 — got {muids}")
            suids = (await superc.get("/sessions/users")).json()
            check(member_id in suids and super_id in suids, "D5: super /sessions/users = 전체 포함")
        finally:
            await member.aclose(); await superc.aclose(); await machine.aclose()
    finally:
        await _cleanup()
        _provision(create=False)

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 067 라이브 통합 — 세션 list·item(404 은폐)·배지·user_ids 스코핑 전부 통과")


asyncio.run(main())
