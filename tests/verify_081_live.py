"""스펙 081 라이브 통합(실 인프라 rung 2) — resync stale endpoint 자가치유.

단위(verify_081_unit)는 전송 폴백·안내 술어만 격리 검증한다. 이 테스트만이 *connect 저장 →
endpoint 손상 → resync 재fetch·재resolve → 교정 → 실제 도달*의 글루를 실 DB(SessionLocal)+실 HTTP
(스레드 서버)로 잡는다 — 사용자의 "외부 에이전트 응답 오류 404"(stale endpoint) 재발 방지의 핵심.

흐름(071 라이브 패턴 재사용 — prefix-마운트 카드):
  1. 스레드 서버: `/proxy/ccab` 하위 well-known 카드(`"url":"/a2a"` 루트상대) + a2a 엔드포인트(POST 200).
  2. connect → 저장 endpoint == prefix/a2a, config["cardUrl"] 저장됨(신규 필드 회귀).
  3. DB endpoint를 옛 버그값(prefix 탈락 …/a2a)으로 손상 → resync → endpoint가 prefix/a2a로 교정.
  4. 교정된 endpoint로 a2a_stream(streaming=False) → mock 텍스트 도달(호출 경로 글루).
  5. 레거시(cardUrl 없는 행) → resync는 endpoint 불변, last_sync만 갱신(no-op 자가치유).

실행: .venv/bin/python tests/verify_081_live.py
"""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import a2a_client, net_guard  # noqa: E402
from api.agents import connect_agent, resync_agent  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent  # noqa: E402
from api.schemas import ConnectAgentIn  # noqa: E402

net_guard._set_allowed_hosts_for_test(["127.0.0.1"])

PREFIX = "/proxy/ccab"
CARD = {
    "name": "Resync Self-Heal Agent (081)",
    "description": "stale endpoint 자가치유 재현 — 카드 루트상대 /a2a.",
    "url": "/a2a",
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [{"id": "s", "name": "s", "description": "d", "tags": []}],
}
MOCK_REPLY = "스펙081 resync 교정 endpoint 도달 OK"

_fails: list[str] = []


def ck(c: bool, m: str) -> None:
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        self.send_response(code)
        if obj is not None:
            body = json.dumps(obj).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):
        if self.path == f"{PREFIX}/.well-known/agent-card.json":
            self._send(200, CARD)
        elif self.path == f"{PREFIX}/a2a":
            self._send(405)
        else:
            self._send(404)

    def do_POST(self):
        if self.path == f"{PREFIX}/a2a":
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, {
                "jsonrpc": "2.0", "id": body.get("id"),
                "result": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": MOCK_REPLY}],
                    "messageId": "m1", "kind": "message",
                },
            })
        else:
            self._send(404)


async def _connect(url):
    async with SessionLocal() as s:
        return await connect_agent(ConnectAgentIn(url=url, token=None), s)


async def _corrupt_endpoint(pk, bad):
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        row.endpoint = bad
        await s.commit()


async def _strip_card_url(pk):
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        cfg = dict(row.config or {})
        cfg.pop("cardUrl", None)
        row.config = cfg
        await s.commit()


async def _resync(pk):
    async with SessionLocal() as s:
        return await resync_agent(pk, s)


async def _get(pk):
    async with SessionLocal() as s:
        return await s.get(Agent, pk)


async def _cleanup(pk):
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        if row is not None:
            await s.delete(row)
            await s.commit()


async def main():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}{PREFIX}"
    want_endpoint = f"http://127.0.0.1:{port}{PREFIX}/a2a"
    bad_endpoint = f"http://127.0.0.1:{port}/a2a"  # prefix 탈락(옛 버그/원격 변경 흉내)

    pk = None
    try:
        out = await _connect(base)
        pk = out.id

        # L1 — connect가 cardUrl을 저장(신규 필드 회귀)
        row = await _get(pk)
        ck(row.config.get("cardUrl") == base,
           f"L1 connect가 config['cardUrl'] 저장 (got={row.config.get('cardUrl')!r})")
        ck(row.endpoint == want_endpoint,
           f"L2 초기 endpoint prefix 보존 (got={row.endpoint})")

        # L3 — endpoint를 옛 버그값으로 손상 → resync로 자가치유
        await _corrupt_endpoint(pk, bad_endpoint)
        mid = await _get(pk)
        ck(mid.endpoint == bad_endpoint, "L3a 손상 적용 확인(prefix 탈락)")
        healed = await _resync(pk)
        ck(healed.endpoint == want_endpoint,
           f"L3b resync 재fetch·재resolve로 endpoint 교정 (want={want_endpoint}, got={healed.endpoint})")
        ck(getattr(healed, "status", None) == "online",
           f"L3c resync가 probe로 status 갱신 online (got={getattr(healed, 'status', None)})")

        # L4 — 교정된 endpoint로 실제 호출 → mock 텍스트 도달(호출 경로 글루)
        texts = []
        async for f in a2a_client.a2a_stream(healed.endpoint, None, "hi", streaming=False, context_id="s1"):
            if "text" in f:
                texts.append(f["text"])
        ck(MOCK_REPLY in "".join(texts), f"L4 교정 endpoint로 호출 → mock 응답 도달 (got={texts!r})")

        # L5 — 레거시(cardUrl 없는 행): resync는 endpoint 불변, last_sync만
        await _corrupt_endpoint(pk, bad_endpoint)
        await _strip_card_url(pk)
        legacy = await _resync(pk)
        ck(legacy.endpoint == bad_endpoint,
           f"L5 레거시(cardUrl 없음) resync는 endpoint 불변 — 재해석 출처 없음 (got={legacy.endpoint})")
        ck(legacy.lastSync == "방금", f"L5 last_sync는 갱신 (got={legacy.lastSync!r})")
    finally:
        if pk is not None:
            await _cleanup(pk)
        srv.shutdown()
        net_guard._set_allowed_hosts_for_test([])

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (8 — cardUrl 저장·초기 endpoint·손상·교정·status·도달·레거시 no-op·last_sync)")


if __name__ == "__main__":
    asyncio.run(main())
