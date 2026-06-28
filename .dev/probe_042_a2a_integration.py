"""스펙 042 rung 2 — A2A 실호출 통합 검증(실 HTTP 라운드트립·실 DB).

verify_042는 a2a_client 파서·SSRF 가드를 *시맨틱*으로 박제했다(네트워크 없음). 이 프로브는 그 위의
**실 outbound 글루**를 증명한다: 진짜 소켓으로 uvicorn을 띄우고, 외부 에이전트의 endpoint를 같은
서버의 mock A2A(`/_remote/a2a`)로 걸어, `/chat` → a2a_client가 실제 JSON-RPC 호출 → SSE 응답을
우리 프레임으로 재전송 → Message 영속·trace(a2a:True)까지.

ASGITransport로는 a2a_client의 outbound httpx 호출이 in-process 앱에 닿지 않으므로(실 소켓 필요)
**진짜 서버**를 띄운다 — 이게 rung 2가 잡는 '요청 간·프로세스 경계' 글루의 핵심.

streaming(message/stream)·non-streaming(message/send) 두 경로 + SSRF 차단(allowlist 밖)을 태운다.

실행: uv run python .dev/probe_042_a2a_integration.py
"""

import asyncio
import json
import os
import sys
import threading
import time
import uuid

# 자가 fixture(스펙 050 Phase 3): 영속 admin042i에 의존하지 말고 던짐용 super를 즉석 시드 → 끝에 삭제.
# 매 실행 고유 이메일이라 충돌·잔존 0(이전엔 admin042i가 영속 정크로 쌓였다).
_PROBE_ADMIN_EMAIL = "probe042_" + uuid.uuid4().hex[:8] + "@example.com"
_PROBE_ADMIN_PW = "Probe042x!pw"
os.environ["ADMIN_EMAIL"] = _PROBE_ADMIN_EMAIL
os.environ["ADMIN_PASSWORD"] = _PROBE_ADMIN_PW
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["A2A_ALLOWED_HOSTS"] = "127.0.0.1,localhost"  # dev allowlist — mock(127.0.0.1) 허용

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from api.db import DATABASE_URL  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Agent, Message, Session  # noqa: E402

# probe 전용 엔진/세션 — app의 SessionLocal은 uvicorn 스레드 루프에 바인딩되므로
# 메인 루프에서 같은 엔진을 쓰면 "different loop" 충돌. 별도 엔진으로 격리한다.
_engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)

PORT = 8142
BASE = f"http://127.0.0.1:{PORT}"
_fails: list[str] = []
_created_agent_pks: list[uuid.UUID] = []  # 자가정리 추적 — finally에서 cascade 삭제(세션·버전 동반)


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _make_card(streaming: bool) -> dict:
    return {
        "name": "Probe A2A Agent",
        "url": f"{BASE}/_remote/a2a",
        "capabilities": {"streaming": streaming, "pushNotifications": False},
        "skills": [{"id": "weather-now", "name": "현재 날씨"}],
    }


async def _make_external_agent(streaming: bool) -> uuid.UUID:
    """source=external 에이전트를 DB에 직접 삽입(endpoint=mock A2A). pk 반환."""
    aid = "agt_a2a_" + uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        a = Agent(
            agent_id=aid,
            name="Probe A2A " + ("stream" if streaming else "send"),
            source="external",
            persona="",
            endpoint=f"{BASE}/_remote/a2a",
            token=None,
            config={"card": _make_card(streaming)},
        )
        db.add(a)
        await db.commit()
        await db.refresh(a)
        _created_agent_pks.append(a.id)
        return a.id


async def _sse_post(client, url, payload):
    frames = []
    async with client.stream("POST", url, json=payload) as resp:
        status = resp.status_code
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                body = line[5:].lstrip()
                if body == "[DONE]":
                    continue
                try:
                    frames.append(json.loads(body))
                except json.JSONDecodeError:
                    pass
            elif line.startswith("event:"):
                frames.append({"_event": line[6:].strip()})
    return status, frames


async def _session_msgs(session_str_id):
    async with SessionLocal() as db:
        s = (
            await db.execute(select(Session).where(Session.session_id == session_str_id))
        ).scalar_one_or_none()
        if s is None:
            return []
        rows = (
            await db.execute(select(Message).where(Message.session_pk == s.id))
        ).scalars().all()
        return [(m.role, m.content) for m in rows]


def _start_server() -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    # 서버 기동 + lifespan(체크포인터·DB) 완료 대기.
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    return server


async def _run_case(client, streaming: bool):
    label = "streaming(message/stream)" if streaming else "non-streaming(message/send)"
    print(f"\n[{label}]")
    pk = await _make_external_agent(streaming)
    status, frames = await _sse_post(
        client, f"/agents/{pk}/chat",
        {"messages": [{"role": "user", "content": "서울 날씨 알려줘"}]},
    )
    check(status == 200, f"chat 200 (got {status})")
    texts = "".join(f.get("text", "") for f in frames)
    errs = "".join(f.get("error", "") for f in frames)
    check("mock-a2a" in texts, f"외부 A2A 응답 텍스트 재전송됨 (got: {texts[:60]!r})")
    check(not errs, f"에러 프레임 없음 (got: {errs[:80]!r})")
    trace = next((f for f in frames if isinstance(f, dict) and f.get("a2a")), None)
    check(trace is not None and trace.get("a2a") is True, "trace에 a2a:True")
    # 세션 id는 서버가 발급(sess-xxxxxx) — 그 프레임 값으로 영속을 확인한다.
    sid = next((f.get("session") for f in frames if "session" in f), None)
    check(bool(sid) and sid.startswith("sess-"), f"session 프레임 발급(got: {sid!r})")
    msgs = await _session_msgs(sid) if sid else []
    check(
        any("mock-a2a" in c for role, c in msgs if role == "assistant"),
        "외부 응답이 세션에 assistant 메시지로 영속",
    )
    check(
        any(c == "서울 날씨 알려줘" for role, c in msgs if role == "user"),
        "user 메시지도 영속",
    )


async def _run_ssrf_block(client):
    """allowlist 밖 사설대역 endpoint는 차단되어 에러 프레임(영속 없음)."""
    print("\n[SSRF 차단 — allowlist 밖 사설]")
    aid = "agt_a2a_blk_" + uuid.uuid4().hex[:6]
    async with SessionLocal() as db:
        a = Agent(
            agent_id=aid, name="Probe A2A blocked", source="external", persona="",
            endpoint="http://10.0.0.5:9999/a2a", token=None,
            config={"card": {"name": "x", "url": "http://10.0.0.5:9999/a2a",
                             "capabilities": {"streaming": True}, "skills": [{"id": "s"}]}},
        )
        db.add(a)
        await db.commit()
        await db.refresh(a)
        _created_agent_pks.append(a.id)
        pk = a.id
    sid = uuid.uuid4().hex
    status, frames = await _sse_post(
        client, f"/agents/{pk}/chat",
        {"sessionId": sid, "messages": [{"role": "user", "content": "hi"}]},
    )
    errs = "".join(f.get("error", "") for f in frames)
    check(status == 200, f"chat 200(스트림 자체는 정상 오픈) (got {status})")
    check("사설" in errs or "차단" in errs, f"SSRF 에러 프레임 emit (got: {errs[:80]!r})")
    msgs = await _session_msgs(sid)
    check(not any(role == "assistant" for role, _ in msgs), "차단 시 응답 미영속(부수효과 0)")


async def _teardown():
    """자가정리(스펙 050 Phase 3) — 이 실행이 만든 external 에이전트(+세션·버전 cascade)와
    던짐용 super를 제거한다. 이전엔 매 실행 3 에이전트·세션·admin042i가 영속 정크로 쌓였다."""
    from sqlalchemy import delete, select, text  # noqa: PLC0415

    from api.models import User  # noqa: PLC0415

    async with SessionLocal() as db:
        if _created_agent_pks:
            # Agent 삭제 → sessions(agent_pk FK CASCADE)·agent_versions 동반 정리.
            await db.execute(delete(Agent).where(Agent.id.in_(_created_agent_pks)))
        uid = (
            await db.execute(select(User.id).where(User.email == _PROBE_ADMIN_EMAIL))
        ).scalar_one_or_none()
        if uid is not None:  # 던짐용 super 제거(casbin grant 방어적 동반).
            await db.execute(
                text("DELETE FROM casbin_rule WHERE ptype IN ('g','p') AND v0 = :u"),
                {"u": str(uid)},
            )
            await db.execute(delete(User).where(User.id == uid))
        await db.commit()
    print(f"  자가정리: 에이전트 {len(_created_agent_pks)} + 던짐 super 1 제거")


async def main():
    server = _start_server()
    try:
        check(server.started, "전제: uvicorn 실서버 기동(실 소켓·실 DB·lifespan)")
        async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
            lc = await client.post(
                "/auth/login",
                data={"username": _PROBE_ADMIN_EMAIL, "password": _PROBE_ADMIN_PW},
            )
            check(lc.status_code == 204, f"admin 로그인 204 (got {lc.status_code})")
            await _run_case(client, streaming=True)
            await _run_case(client, streaming=False)
            await _run_ssrf_block(client)
    finally:
        await _teardown()  # 자가정리 — 만든 에이전트·세션·던짐 super 제거(정크 무축적)
        server.should_exit = True
        time.sleep(0.5)

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 042 A2A 실호출 통합 전부 통과(stream·send·영속·trace·SSRF 차단)")


asyncio.run(main())
