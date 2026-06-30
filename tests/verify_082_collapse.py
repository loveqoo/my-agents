"""스펙 082 — endpoint resolution 꼬리 중복(`/a2a/a2a`) collapse 검증.

rung1 단위: _resolve_card_endpoint 매트릭스(버그 3행 collapse·정상 3행 무회귀·다중꼬리·부분겹침).
rung2 라이브: prefix=/a2a 마운트 스레드 서버(카드 url 루트상대 /a2a) → connect → 저장 endpoint가
  `…/a2a`(중복 아님)·probe live·그 endpoint로 POST 도달. 071 라이브(/proxy/ccab)는 verify_071_live가 커버.

실행: .venv/bin/python tests/verify_082_collapse.py
"""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import net_guard  # noqa: E402
from api.agent_card import _resolve_card_endpoint  # noqa: E402
from api.agents import connect_agent  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent  # noqa: E402
from api.schemas import ConnectAgentIn  # noqa: E402

net_guard._set_allowed_hosts_for_test(["127.0.0.1"])

_fails: list[str] = []


def ck(c, m):
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


def test_unit():
    cases = [
        ("kakaopay prefix(무회귀)", "/a2a", "http://h:8000/proxy/ccab/.well-known/agent-card.json", "http://h:8000/proxy/ccab/a2a"),
        ("prefix=/a2a + 루트상대(collapse)", "/a2a", "http://h:8000/a2a/.well-known/agent-card.json", "http://h:8000/a2a"),
        ("bare a2a + prefix /a2a(collapse)", "a2a", "http://h:8000/a2a/.well-known/agent-card.json", "http://h:8000/a2a"),
        ("base=/a2a 직접 서빙(collapse)", "/a2a", "http://h:8000/a2a", "http://h:8000/a2a"),
        ("절대 url(무회귀)", "http://h:8000/a2a", "http://h:8000/a2a/.well-known/agent-card.json", "http://h:8000/a2a"),
        ("표준 root + 루트상대(무회귀)", "/a2a", "http://h:8000/.well-known/agent-card.json", "http://h:8000/a2a"),
        ("다중 꼬리 /v1/a2a collapse", "/v1/a2a", "http://h:8000/svc/v1/a2a/.well-known/agent-card.json", "http://h:8000/svc/v1/a2a"),
        ("부분겹침 a2a/rpc(미collapse)", "a2a/rpc", "http://h:8000/a2a/.well-known/agent-card.json", "http://h:8000/a2a/a2a/rpc"),
    ]
    for desc, raw, cand, want in cases:
        got = _resolve_card_endpoint(raw, cand)
        ck(got == want, f"U {desc} (got={got})")


PREFIX = "/a2a"
CARD = {
    "name": "Tail-Collapse Agent (082)",
    "description": "prefix=/a2a 마운트 + 카드 루트상대 /a2a — 중복 collapse 재현.",
    "url": "/a2a",  # 루트상대 — prefix가 이미 /a2a라 071대로면 /a2a/a2a 중복
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [{"id": "s", "name": "s", "description": "d", "tags": []}],
}
MOCK_REPLY = "스펙082 collapse endpoint 도달 OK"


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
        elif self.path == PREFIX:
            self._send(405)  # a2a 엔드포인트 존재·GET 불가 → probe live(404 아님)
        else:
            self._send(404)

    def do_POST(self):
        if self.path == PREFIX:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, {
                "jsonrpc": "2.0", "id": body.get("id"),
                "result": {"role": "agent",
                           "parts": [{"kind": "text", "text": MOCK_REPLY}],
                           "messageId": "m1", "kind": "message"},
            })
        else:
            self._send(404)


async def _connect(url):
    async with SessionLocal() as s:
        return await connect_agent(ConnectAgentIn(url=url, token=None), s)


async def _cleanup(pk):
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        if row is not None:
            await s.delete(row)
            await s.commit()


async def test_live():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}{PREFIX}"            # 사용자가 /a2a까지 입력
    want = f"http://127.0.0.1:{port}{PREFIX}"            # 교정: 중복 없이 /a2a
    doubled = f"http://127.0.0.1:{port}{PREFIX}/a2a"     # 버그값
    pk = None
    try:
        out = await _connect(base)
        pk = out.id
        ck(out.endpoint == want, f"L1 저장 endpoint 중복 없음 (want={want}, got={out.endpoint})")
        ck(out.endpoint != doubled, "L2 옛 버그값(/a2a/a2a) 아님")
        ck(getattr(out, "status", None) == "online", f"L3 probe live (got={getattr(out,'status',None)})")
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(out.endpoint, json={
                "jsonrpc": "2.0", "id": "1", "method": "message/send",
                "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}}})
            txt = ""
            if r.status_code == 200:
                parts = (r.json().get("result") or {}).get("parts") or []
                txt = "".join(p.get("text", "") for p in parts)
        ck(MOCK_REPLY in txt, f"L4 교정 endpoint로 POST 도달 (got={txt!r})")
    finally:
        if pk is not None:
            await _cleanup(pk)
        srv.shutdown()


async def main():
    test_unit()
    await test_live()
    net_guard._set_allowed_hosts_for_test([])
    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (단위 8 매트릭스 + 라이브 4 도달)")


if __name__ == "__main__":
    asyncio.run(main())
