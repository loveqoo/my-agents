"""스펙 209 검증(라이브 통합) — 응답 피드백(👍/👎) 수집을 실 HTTP 위에서.

verify_067_live 패턴 재사용(글루 증명): 실 쿠키 principal(member/super), 머신 Bearer, DB 스코핑.
피드백 입구의 소유권 경계를 실측한다 — 세션 소유자만 자기 세션 assistant 메시지에 피드백,
타인 세션·비-assistant·부재는 동일 404(은폐), 머신/익명은 403(owner_id 원천 없음), upsert 1건.

전제: API(127.0.0.1:8000)+실 DB 생존. 던짐용 계정·합성 데이터 즉석 생성/삭제.
실행: .venv/bin/python tests/verify_209_feedback.py  (API 서버 떠 있어야 함)
"""
import asyncio
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api.db import SessionLocal  # noqa: E402
from api.models import Agent, Message, MessageFeedback, Session, User  # noqa: E402

BASE = "http://127.0.0.1:8000"
MACHINE = (os.environ.get("API_AUTH_TOKEN") or "").strip()
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")

MEMBER_EMAIL = "probe209m@example.com"
SUPER_EMAIL = "probe209s@example.com"
PW = "Probe209-pw!"
AGENT_ID = "agt-209t"
SPREFIX = "sess-209t-"

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
    """합성 Agent 1 + Session 2(member own·super own), 각 세션에 user+assistant 메시지."""
    ids: dict = {}
    async with SessionLocal() as s:
        agent = Agent(agent_id=AGENT_ID, name="probe209", source="ui")
        s.add(agent)
        await s.flush()
        for k, owner in {"own": member_id, "others": super_id}.items():
            sid = f"{SPREFIX}{k}"
            sess = Session(session_id=sid, agent_pk=agent.id, agent_name="probe209",
                           user_id=owner, status="active")
            s.add(sess)
            await s.flush()
            um = Message(session_pk=sess.id, role="user", content=f"질문-{k}")
            am = Message(session_pk=sess.id, role="assistant", content=f"답변-{k}")
            s.add(um)
            s.add(am)
            await s.flush()
            ids[k] = {"sid": sid, "user_mid": str(um.id), "asst_mid": str(am.id)}
        await s.commit()
    return ids


async def _cleanup() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(Session).where(Session.session_id.like(f"{SPREFIX}%")))
        await s.execute(delete(Agent).where(Agent.agent_id == AGENT_ID))
        await s.commit()


async def _login(client: httpx.AsyncClient, email: str) -> bool:
    r = await client.post("/auth/login", data={"username": email, "password": PW},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.status_code in (200, 204)


async def _fb_count(asst_mid: str) -> int:
    async with SessionLocal() as s:
        return (await s.execute(
            select(func.count()).select_from(MessageFeedback).where(MessageFeedback.message_pk == asst_mid)
        )).scalar_one()


async def main() -> None:
    if not MACHINE:
        print("❌ 전제 실패 — API_AUTH_TOKEN 미설정(.env). 종료.")
        sys.exit(1)
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as mc:
        mc.headers["Authorization"] = f"Bearer {MACHINE}"
        pre = await mc.get("/sessions", params={"limit": 1})
        check(pre.status_code == 200, f"PRE: 머신 GET /sessions 200 — got {pre.status_code}")
        if pre.status_code != 200:
            print("❌ 전제 실패. 종료."); sys.exit(1)

    _provision(create=True)
    try:
        async with SessionLocal() as s:
            member_id = await _uid(s, MEMBER_EMAIL)
            super_id = await _uid(s, SUPER_EMAIL)
        ids = await _seed(member_id, super_id)
        own = ids["own"]
        others = ids["others"]

        member = httpx.AsyncClient(base_url=BASE, timeout=10)
        superc = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine.headers["Authorization"] = f"Bearer {MACHINE}"
        try:
            check(await _login(member, MEMBER_EMAIL), "SETUP: member 로그인")
            check(await _login(superc, SUPER_EMAIL), "SETUP: super 로그인")

            def fb_url(d, mid_key="asst_mid"):
                return f"/sessions/{d['sid']}/messages/{d[mid_key]}/feedback"

            # ---- H1 소유자 upsert happy path ----
            r = await member.put(fb_url(own), json={"rating": "up"})
            check(r.status_code == 200 and r.json()["rating"] == "up", f"H1: 소유자 👍 set → 200 up — got {r.status_code}/{r.text[:80]}")

            msgs = (await member.get(f"/sessions/{own['sid']}/messages")).json()
            asst = next((m for m in msgs if m["id"] == own["asst_mid"]), None)
            check(asst is not None and asst.get("feedback", {}) and asst["feedback"]["rating"] == "up",
                  f"H2: /messages에 내 피드백(up) 반영 — got {asst and asst.get('feedback')}")

            # ---- H3 upsert 토글(👍→👎), 1건 유지 ----
            r = await member.put(fb_url(own), json={"rating": "down", "reason": "사실 오류"})
            check(r.status_code == 200 and r.json()["rating"] == "down" and r.json()["reason"] == "사실 오류",
                  f"H3: 토글 👎+이유 → 200 down — got {r.status_code}/{r.text[:80]}")
            cnt = await _fb_count(own["asst_mid"])
            check(cnt == 1, f"H3: upsert=1건 유지(중복 미생성) — got {cnt}")

            # ---- B1 비-assistant 메시지에 피드백 → 404 ----
            r = await member.put(f"/sessions/{own['sid']}/messages/{own['user_mid']}/feedback", json={"rating": "up"})
            check(r.status_code == 404, f"B1: user 메시지 피드백 → 404(assistant만) — got {r.status_code}")

            # ---- B2 부재 메시지 → 404 ----
            r = await member.put(f"/sessions/{own['sid']}/messages/00000000-0000-0000-0000-000000000000/feedback", json={"rating": "up"})
            check(r.status_code == 404, f"B2: 부재 메시지 → 404 — got {r.status_code}")

            # ---- O1 타인 세션 메시지에 피드백 → 404(은폐), 실제 미생성 ----
            r = await member.put(fb_url(others), json={"rating": "up"})
            check(r.status_code == 404, f"O1(T): member 타인 세션 피드백 → 404(은폐) — got {r.status_code}")
            check(await _fb_count(others["asst_mid"]) == 0, "O1(T): 타인 메시지 피드백 실제 미생성(주입 차단)")

            # ---- O2 머신 Bearer → 403(owner_id 원천 없음) ----
            r = await machine.put(fb_url(own), json={"rating": "up"})
            check(r.status_code == 403, f"O2: 머신 토큰 피드백 → 403(로그인 사용자만) — got {r.status_code}")

            # ---- O3 super(admin)는 임의 세션 피드백 가능(스코프 None) ----
            r = await superc.put(fb_url(own), json={"rating": "up"})
            check(r.status_code == 200, f"O3: super(admin) 임의 세션 피드백 → 200 — got {r.status_code}")
            check(await _fb_count(own["asst_mid"]) == 2, "O3: member+super 각자 1건(owner_id별 분리)")

            # ---- F3(codex) reason 상한 → 422(무제한 저장 팽창 차단) ----
            r = await member.put(fb_url(own), json={"rating": "up", "reason": "x" * 3000})
            check(r.status_code == 422, f"F3: reason 3000자 → 422(상한) — got {r.status_code}")

            # ---- H4 DELETE로 취소 → 피드백 None, 내 행만 삭제 ----
            r = await member.delete(fb_url(own))
            check(r.status_code == 204, f"H4: DELETE → 204 — got {r.status_code}")
            msgs = (await member.get(f"/sessions/{own['sid']}/messages")).json()
            asst = next((m for m in msgs if m["id"] == own["asst_mid"]), None)
            check(asst is not None and not asst.get("feedback"), "H4: 내 피드백 취소 반영(None)")
            check(await _fb_count(own["asst_mid"]) == 1, "H4: 내 행만 삭제(super 행 잔존=1)")
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
    print("✅ 스펙 209 라이브 통합 — 피드백 upsert·소유권 404 은폐·assistant-only·머신 403·DELETE 전부 통과")


asyncio.run(main())
