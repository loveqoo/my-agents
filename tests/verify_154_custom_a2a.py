"""verify_154 — 커스텀 에이전트 A2A 공개 (스펙 154, 실사용 #3 + 백로그 ③).

  V1 승격/강등: owner→None / 재스탬프·A2A 자동 off·no-takeover·머신 강등 400·비소유 404-fold.
  V2 ui+impl 루프백: public 커스텀 플로우(research-pipeline-demo) 노출 → ASGI 카드+message/send 실행.
  V3 code 중계: mock A2A(/_remote/a2a)로 등록한 code 에이전트 노출 → ASGI 호출 → 중계 응답.
  V4 루프 가드: x-my-agents-relay 헤더 요청 → -32000(1홉 한정).
  V5 external 노출 400(152 무회귀 핀).
실행: uv run --project packages/api --env-file .env python tests/verify_154_custom_a2a.py
※ mock(/_remote/*)이 실 서버(127.0.0.1:8000)를 향하므로 API가 떠 있어야 한다.
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import agents as AG  # noqa: E402
from api import crypto  # noqa: E402
from api.models import Agent  # noqa: E402
from api.schemas import ExposeIn  # noqa: E402

_fails = []
passed = 0
TOKEN = os.environ.get("API_AUTH_TOKEN", "")


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _P:
    def __init__(self, superuser=False):
        self.id = _uuid.uuid4()
        self.is_superuser = superuser


def _rpc_body(text: str) -> dict:
    return {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": text}]}},
    }


async def main():
    from api.authz import init_authz
    await init_authz()
    admin = _P(superuser=True)
    member = _P()
    tag = f"v154-{_uuid.uuid4().hex[:6]}"
    made: list = []
    restore_pe = None  # research-pipeline-demo exposed 원복

    try:
        # ---- V1 승격/강등 ----
        async with async_session() as s:
            a = Agent(agent_id=f"{tag}-vis", name=f"{tag}-vis", source="ui",
                      owner_id=str(member.id), config={"model": "", "prompt": ""},
                      exposed={"a2a": False})
            s.add(a)
            await s.commit()
            made.append(a.id)
        async with async_session() as s:
            out = await AG.set_agent_visibility(made[0], AG.VisibilityIn(public=True),
                                                session=s, principal=member)
            check(out.owner_id is None, "V1a 소유자 본인 승격 → owner None")
        async with async_session() as s:
            await AG.expose_agent(made[0], ExposeIn(a2a=True), session=s, principal=admin)
        async with async_session() as s:
            out = await AG.set_agent_visibility(made[0], AG.VisibilityIn(public=False),
                                                session=s, principal=admin)
            check(out.owner_id == str(admin.id) and out.exposed.get("a2a") is False,
                  "V1b 강등 → 재스탬프 + A2A 자동 off")
        async with async_session() as s:
            out = await AG.set_agent_visibility(made[0], AG.VisibilityIn(public=False),
                                                session=s, principal=admin)
            check(out.owner_id == str(admin.id), "V1c 이미 private 강등 → 소유자 보존(no-takeover)")
        async with async_session() as s:
            try:
                await AG.set_agent_visibility(made[0], AG.VisibilityIn(public=True),
                                              session=s, principal=member)
                check(False, "V1d 비소유 member 전환 → 404-fold이어야")
            except HTTPException as e:
                check(e.status_code == 404, f"V1d 비소유 404-fold (got {e.status_code})")
        async with async_session() as s:
            await AG.set_agent_visibility(made[0], AG.VisibilityIn(public=True), session=s, principal=admin)
        async with async_session() as s:
            try:
                await AG.set_agent_visibility(made[0], AG.VisibilityIn(public=False),
                                              session=s, principal="machine")
                check(False, "V1e 머신 강등 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V1e 머신 강등 400 (got {e.status_code})")

        # ---- V2 ui+impl 루프백(공통 인터페이스 구현체) ----
        from api.main import app
        async with async_session() as s:
            pe = (await s.execute(select(Agent).where(Agent.name == "research-pipeline-demo"))).scalar_one_or_none()
            # 스펙 327: 시드 데모가 노드형(pipeline)으로 대체 — ui+impl 커스텀 플로우라는 검증 목적은 동일.
            check(pe is not None and (pe.config or {}).get("impl") == "pipeline", "V2a 시드 커스텀 플로우 존재(ui+impl)")
            restore_pe = dict(pe.exposed or {})
            pe.exposed = {**(pe.exposed or {}), "a2a": True}
            await s.commit()
            pe_id = pe.id
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=120) as c:
            r = await c.get(f"/agents/{pe_id}/.well-known/agent-card.json")
            check(r.status_code == 200, f"V2b 커스텀 플로우 카드 200 (got {r.status_code})")
            r = await c.post(f"/agents/{pe_id}/a2a", json=_rpc_body("A2A 루프백 스모크"), headers=headers)
            reply = ((r.json().get("result") or {}).get("parts") or [{}])[0].get("text", "")
            check(r.status_code == 200 and len(reply) > 0 and "error" not in r.json(),
                  f"V2c 커스텀 플로우 A2A 실행(impl 해석) — 응답 {len(reply)}자")

        # ---- V3 code 중계 ----
        remote_base = os.environ.get("REMOTE_AGENT_BASE", "http://127.0.0.1:8000/_remote/a2a")
        async with async_session() as s:
            ca = Agent(agent_id=f"{tag}-code", name=f"{tag}-code", source="code",
                       owner_id=None, config={"model": "", "prompt": ""},
                       exposed={"a2a": False}, endpoint=remote_base,
                       token=crypto.encrypt("sk_live_demo"))
            s.add(ca)
            await s.commit()
            made.append(ca.id)
        async with async_session() as s:
            out = await AG.expose_agent(made[-1], ExposeIn(a2a=True), session=s, principal=admin)
            check(out.exposed.get("a2a") is True, "V3a code 에이전트 A2A 켜기 허용(154 완화)")
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=120) as c:
            r = await c.post(f"/agents/{made[-1]}/a2a", json=_rpc_body("중계 스모크"), headers=headers)
            body = r.json()
            reply = ((body.get("result") or {}).get("parts") or [{}])[0].get("text", "")
            check(r.status_code == 200 and len(reply) > 0 and "error" not in body,
                  f"V3b 중계 응답 수신 — {len(reply)}자: {reply[:40]!r}")

            # ---- V4 루프 가드 ----
            r = await c.post(f"/agents/{made[-1]}/a2a", json=_rpc_body("루프"),
                             headers={**headers, "x-my-agents-relay": "1"})
            err = (r.json().get("error") or {})
            check(err.get("code") == -32000 and "루프" in str(err.get("message")),
                  f"V4 중계 루프 거부 (got {err})")

        # ---- V5 external 노출 400(152 무회귀) ----
        async with async_session() as s:
            ea = Agent(agent_id=f"{tag}-ext", name=f"{tag}-ext", source="external",
                       config={"model": "", "prompt": ""}, exposed={"a2a": False})
            s.add(ea)
            await s.commit()
            made.append(ea.id)
        async with async_session() as s:
            try:
                await AG.expose_agent(made[-1], ExposeIn(a2a=True), session=s, principal=admin)
                check(False, "V5 external 노출 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V5 external 노출 400 (got {e.status_code})")
    finally:
        async with async_session() as s:
            if restore_pe is not None:
                pe = (await s.execute(select(Agent).where(Agent.name == "research-pipeline-demo"))).scalar_one_or_none()
                if pe is not None:
                    pe.exposed = restore_pe
            for aid in made:
                a = await s.get(Agent, aid)
                if a is not None:
                    await s.delete(a)
            await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())
