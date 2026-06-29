"""스펙 068 검증(라이브 통합) — chat resume 소유권 경계를 실 HTTP+DB 위에서.

067 게이트를 우회하던 chat resume 입구(`POST /agents/{id}/chat`)가 봉인됐는지, 067이 못 막는
*공격 경로 그 자체*를 실 서버에 던져 증명한다. unit(verify_068_owner.py)이 _next_owner 불변식을
격리 증명한다면, 여기선 **principal→own 글루 + D1 resume 스코프 질의 + D3 영속 불변식**이 실
HTTP·실 mock-llm 턴·실 DB 위에서 함께 작동하는지 본다(learning 069: 읽기 게이트 vs 쓰기 입구).

전제: API(127.0.0.1:8000)+실 DB 생존, 기본 chat 모델=mock-llm(스펙 059). 던짐용 member B 계정·
합성 Agent(ui, mock-llm 폴백)+Session 3종(victim=타 소유 UUID·null-owner·B 본인). 공격 시나리오:
member B가 *타인/추측* session_id로 chat → 새 세션 발급(오라클 제거)·피해자 행 무변경(탈취·오염 0),
B 본인 세션은 정상 resume(무회귀).

실행: .venv/bin/python tests/verify_068_live.py  (API 서버 떠 있어야 함)
"""
import asyncio
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api.chat import _create_approval  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent, Message, Session, User  # noqa: E402

BASE = "http://127.0.0.1:8000"
MACHINE = (os.environ.get("API_AUTH_TOKEN") or "").strip()
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")

MEMBER_EMAIL = "probe068b@example.com"   # 공격자(비-admin member)
PW = "Probe068-pw!"
AGENT_ID = "agt-068t"
SPREFIX = "sess-068t-"
VICTIM_UID = "victim-068-0000-0000-0000-000000000000"  # Session.user_id는 FK 없는 str 컬럼

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _provision(create: bool) -> None:
    args = [PY, PROV, "create", MEMBER_EMAIL, PW, "member"] if create \
        else [PY, PROV, "delete", MEMBER_EMAIL]
    subprocess.run(args, check=False, capture_output=True, text=True)


async def _uid(session, email: str) -> str:
    return str((await session.execute(select(User.id).where(User.email == email))).scalar_one())


async def _seed(member_id: str) -> dict:
    """합성 Agent(ui) 1 + Session 3종(victim 타 소유·null-owner·B 본인) + 각 user 메시지 1건."""
    ids = {}
    async with SessionLocal() as s:
        agent = Agent(agent_id=AGENT_ID, name="probe068", source="ui")
        s.add(agent)
        await s.flush()
        rows = {"victim": VICTIM_UID, "null_owner": None, "b_own": member_id}
        for k, owner in rows.items():
            sid = f"{SPREFIX}{k}"
            ids[k] = sid
            sess = Session(session_id=sid, agent_pk=agent.id, agent_name="probe068",
                           user_id=owner, status="active")
            s.add(sess)
            await s.flush()
            s.add(Message(session_pk=sess.id, role="user", content=f"비밀-{k}"))
        await s.commit()
    return ids


async def _cleanup() -> None:
    """Agent 삭제 → 모든 세션(시드 3종 + 공격이 새로 민팅한 sess-* 행) CASCADE 정리."""
    async with SessionLocal() as s:
        await s.execute(delete(Agent).where(Agent.agent_id == AGENT_ID))
        await s.commit()


async def _login(client: httpx.AsyncClient, email: str) -> bool:
    r = await client.post("/auth/login", data={"username": email, "password": PW},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.status_code in (200, 204)


async def _chat_session_echo(client: httpx.AsyncClient, agent_uuid: str, session_id: str) -> str | None:
    """chat SSE를 던지고 첫 프레임의 'session' 에코를 회수한다(없으면 None).

    로컬(ui) chat은 `data: {"session": <id>}`로 세션 id를 돌려준다(chat.py:560). 추측 적중 id가
    새 id와 *구별*되던 게 열거 오라클이었다 — 068 후 비-admin엔 둘 다 새 id로 수렴해야 한다.
    """
    body = {"messages": [{"role": "user", "content": "ping"}], "sessionId": session_id}
    async with client.stream("POST", f"/agents/{agent_uuid}/chat", json=body) as r:
        if r.status_code != 200:
            return f"HTTP_{r.status_code}"
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                try:
                    obj = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and "session" in obj:
                    return obj["session"]
    return None


async def _row(s, sid: str):
    return (await s.execute(select(Session.user_id, Session.id).where(Session.session_id == sid))).first()


async def _msgcount(s, session_pk) -> int:
    return (await s.execute(select(func.count(Message.id)).where(Message.session_pk == session_pk))).scalar_one()


async def main() -> None:
    if not MACHINE:
        print("❌ 전제 실패 — API_AUTH_TOKEN 미설정(.env). 종료."); sys.exit(1)
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as mc:
        mc.headers["Authorization"] = f"Bearer {MACHINE}"
        pre = await mc.get("/sessions", params={"limit": 1})
        check(pre.status_code == 200, f"PRE: 서버 생존 — got {pre.status_code}")
        if pre.status_code != 200:
            print("❌ 전제 실패 — 서버/토큰. 종료."); sys.exit(1)

    _provision(create=True)
    try:
        async with SessionLocal() as s:
            member_id = await _uid(s, MEMBER_EMAIL)
        ids = await _seed(member_id)

        # 시드 직후 피해자 행 스냅샷(공격 전 기준선)
        async with SessionLocal() as s:
            v_uid0, v_pk = await _row(s, ids["victim"])
            v_msgs0 = await _msgcount(s, v_pk)
            n_uid0, n_pk = await _row(s, ids["null_owner"])
            n_msgs0 = await _msgcount(s, n_pk)
        check(v_uid0 == VICTIM_UID, "SETUP: victim 세션 소유자=VICTIM_UID")

        # 공격할 에이전트의 UUID(라우트는 UUID pk를 받음)
        async with SessionLocal() as s:
            agent_uuid = str((await s.execute(
                select(Agent.id).where(Agent.agent_id == AGENT_ID))).scalar_one())

        member = httpx.AsyncClient(base_url=BASE, timeout=30)
        try:
            check(await _login(member, MEMBER_EMAIL), "SETUP: member B 로그인(쿠키)")

            # ---- T1 열거 오라클 제거: B가 타인(victim) session_id로 chat → 새 세션 ----
            echo_v = await _chat_session_echo(member, agent_uuid, ids["victim"])
            check(echo_v is not None and not str(echo_v).startswith("HTTP_"),
                  f"T1: B의 chat 응답에 session 에코 존재 — got {echo_v}")
            check(echo_v != ids["victim"],
                  f"T1(★): B가 타인 session_id resume → 새 세션 발급(에코≠피해자 id) — got {echo_v}")
            check(str(echo_v).startswith("sess-"),
                  f"T1: 발급된 세션은 새 sess-* id — got {echo_v}")

            # ---- T2 소유권 탈취·오염 0: 피해자 행 무변경 ----
            async with SessionLocal() as s:
                v_uid1, _ = await _row(s, ids["victim"])
                v_msgs1 = await _msgcount(s, v_pk)
            check(v_uid1 == VICTIM_UID,
                  f"T2(★): 공격 후 victim 소유자 무변경(탈취 봉인) — got {v_uid1}")
            check(v_msgs1 == v_msgs0,
                  f"T2(★): victim 메시지 수 무변경(오염 0) — {v_msgs0}→{v_msgs1}")

            # ---- T4 NULL-owner 주장 차단: B가 null-owner session_id로 chat → 새 세션 ----
            echo_n = await _chat_session_echo(member, agent_uuid, ids["null_owner"])
            check(echo_n != ids["null_owner"],
                  f"T4: B가 NULL-owner session_id resume → 새 세션(주장 차단) — got {echo_n}")
            async with SessionLocal() as s:
                n_uid1, _ = await _row(s, ids["null_owner"])
                n_msgs1 = await _msgcount(s, n_pk)
            check(n_uid1 is None and n_msgs1 == n_msgs0,
                  f"T4: NULL-owner 행 무변경(소유자 None 유지·메시지 {n_msgs0}→{n_msgs1})")

            # ---- T6 무회귀: B가 *자기* 세션 resume → 같은 id 에코, 소유자 유지 ----
            echo_b = await _chat_session_echo(member, agent_uuid, ids["b_own"])
            check(echo_b == ids["b_own"],
                  f"T6(무회귀): B가 본인 세션 resume → 같은 session_id 에코 — got {echo_b}")
            async with SessionLocal() as s:
                b_uid1, _ = await _row(s, ids["b_own"])
            check(b_uid1 == member_id,
                  f"T6: B 본인 세션 소유자 유지 — got {b_uid1}")

            # ---- D6 무회귀: 승인 게이트가 만든 세션은 *생성 시점*에 시작 주체로 소유된다 ----
            # codex 적대(P3-2): _create_approval가 NULL-owned 행을 만들면 D1 도입 후 시작 member가
            # 자기 세션을 못 이어간다. D6가 생성 시점에 owner를 박는지 직접 호출로 검증.
            async with SessionLocal() as s:
                agent_pk = (await s.execute(
                    select(Agent.id).where(Agent.agent_id == AGENT_ID))).scalar_one()
            apr_sid = f"{SPREFIX}approval"
            apr_ctx = {
                "session_pk": None,
                "session_pending": {"session_id": apr_sid, "agent_pk": agent_pk,
                                    "agent_name": "probe068", "channel": "playground"},
                "session_id": apr_sid, "agent_pk": agent_pk, "agent_name": "probe068",
            }
            await _create_approval(apr_ctx, "thr-068t", {"permission": "data.read",
                                   "action": "test", "args": {}, "summary": "s"}, member_id)
            async with SessionLocal() as s:
                a_uid, _ = await _row(s, apr_sid)
            check(a_uid == member_id,
                  f"D6(★): 승인 생성 세션은 시작 주체 소유(NULL-owned 아님) — got {a_uid}")
            echo_apr = await _chat_session_echo(member, agent_uuid, apr_sid)
            check(echo_apr == apr_sid,
                  f"D6(무회귀): member가 자기 승인-세션 resume → 같은 id 에코 — got {echo_apr}")
        finally:
            await member.aclose()
    finally:
        await _cleanup()
        _provision(create=False)

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 068 라이브 통합 — chat resume 오라클 제거·탈취 봉인·NULL 차단·본인 resume 무회귀 통과")


asyncio.run(main())
