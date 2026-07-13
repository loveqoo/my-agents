"""verify_155 — 플레이그라운드 A2A 루프백 테스트 (스펙 155, 실사용 #8).

플레이그라운드가 A2A 모드에서 호출하는 서버 경로(message/stream SSE)를 실측한다.
클라 파서(handleA2AFrame)·토글 노출/부재는 e2e가 실 브라우저로 검증(별도).

  V1 노출 ui 에이전트 message/stream → status-update 텍스트 프레임 누적 + final + [DONE].
  V2 노출 code 에이전트 message/stream → 중계 프레임 수신(원격 mock).
  V3 루프 가드: x-my-agents-relay 헤더 단 message/stream → -32000 error 프레임.
  V4 미노출 에이전트 message/stream → 404(게이트, 존재 비노출).
실행: uv run --project packages/api --env-file .env python tests/verify_155_playground_a2a.py
※ mock(/_remote/*)이 실 서버(127.0.0.1:8000)를 향하므로 API가 떠 있어야 한다.
"""
import asyncio
import json
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import crypto  # noqa: E402
from api.models import Agent  # noqa: E402

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


def _stream_body(text: str) -> dict:
    return {
        "jsonrpc": "2.0", "id": 1, "method": "message/stream",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": text}]}},
    }


def _parse_sse(raw: str):
    """서버 SSE(data: {json}\\n\\n) → (texts, final_seen, done_seen, error). 클라 파서와 동형."""
    texts, final_seen, done_seen, error = [], False, False, None
    for frame in raw.split("\n\n"):
        line = next((ln for ln in frame.split("\n") if ln.startswith("data: ")), None)
        # data: 없으면 평문 JSON-RPC error 바디(루프 가드 등) — 통째로 파싱(클라 파서와 동형).
        data = line[6:] if line else frame.strip()
        if not data:
            continue
        if data == "[DONE]":
            done_seen = True
            continue
        try:
            obj = json.loads(data)
        except Exception:
            continue
        if obj.get("error"):
            error = obj["error"]
            continue
        result = obj.get("result") or {}
        if result.get("kind") == "status-update":
            for p in (result.get("status", {}).get("message", {}).get("parts") or []):
                if p.get("kind") == "text" and p.get("text"):
                    texts.append(p["text"])
            if result.get("final") is True:
                final_seen = True
    return "".join(texts), final_seen, done_seen, error


async def _post_stream(client, url, body, headers):
    async with client.stream("POST", url, json=body, headers=headers) as r:
        chunks = [c async for c in r.aiter_text()]
        return r.status_code, "".join(chunks)


async def main():
    from api.authz import init_authz
    from api.main import app
    await init_authz()
    tag = f"v155-{_uuid.uuid4().hex[:6]}"
    made: list = []
    restore_pe = None

    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        # ---- V1 노출 ui(커스텀 플로우) message/stream ----
        async with async_session() as s:
            pe = (await s.execute(select(Agent).where(Agent.name == "research-pipeline-demo"))).scalar_one_or_none()
            check(pe is not None, "V1a 시드 커스텀 플로우(research-pipeline-demo) 존재")
            restore_pe = dict(pe.exposed or {})
            pe.exposed = {**(pe.exposed or {}), "a2a": True}
            await s.commit()
            pe_id = pe.id
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=120) as c:
            code, raw = await _post_stream(c, f"/agents/{pe_id}/a2a", _stream_body("A2A 스트림 스모크"), headers)
            reply, final_seen, done_seen, err = _parse_sse(raw)
            check(code == 200 and len(reply) > 0 and err is None,
                  f"V1b ui message/stream 텍스트 수신 — {len(reply)}자, err={err}")
            check(final_seen and done_seen, f"V1c final+[DONE] 종결 (final={final_seen}, done={done_seen})")

            # ---- V4 미노출 에이전트 게이트(먼저: pe만 노출, 임의 UUID는 404) ----
            code, _ = await _post_stream(c, f"/agents/{_uuid.uuid4()}/a2a", _stream_body("x"), headers)
            check(code == 404, f"V4 미노출/부재 에이전트 message/stream 404 (got {code})")

        # ---- V2 노출 code 에이전트 중계 ----
        remote_base = os.environ.get("REMOTE_AGENT_BASE", "http://127.0.0.1:8000/_remote/a2a")
        async with async_session() as s:
            ca = Agent(agent_id=f"{tag}-code", name=f"{tag}-code", source="code",
                       owner_id=None, config={"model": "", "persona": ""},
                       exposed={"a2a": True}, endpoint=remote_base,
                       token=crypto.encrypt("sk_live_demo"))
            s.add(ca)
            await s.commit()
            made.append(ca.id)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=120) as c:
            code, raw = await _post_stream(c, f"/agents/{made[-1]}/a2a", _stream_body("중계 스트림"), headers)
            reply, final_seen, done_seen, err = _parse_sse(raw)
            check(code == 200 and len(reply) > 0 and err is None,
                  f"V2 code message/stream 중계 수신 — {len(reply)}자")

            # ---- V3 루프 가드 ----
            code, raw = await _post_stream(
                c, f"/agents/{made[-1]}/a2a", _stream_body("루프"),
                {**headers, "x-my-agents-relay": "1"})
            _, _, _, err = _parse_sse(raw)
            check(err and err.get("code") == -32000,
                  f"V3 중계 루프 거부 -32000 (got {err})")
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
