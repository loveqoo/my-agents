"""스펙 071 라이브 통합(실 인프라) — prefix-마운트 카드의 endpoint가 prefix를 보존하는가.

비겹침 사다리의 통합 rung(메모리 verification-ladder): *카드 fetch → resolve → 저장 → 도달*의 글루를
실 DB(SessionLocal)+실 HTTP(스레드 서버)로 검증한다. 단위(verify_071)는 resolve 함수만 순수 검증하지만,
이 테스트만이 "프록시 path-prefix 배포(카드가 루트상대 `/a2a` 발행)를 connect로 등록하면 저장 endpoint가
prefix를 보존하고 그 endpoint가 실제 도달 가능한가"를 잡는다 — 실제 장애(카카오페이 sandbox 404) 재현.

흐름:
  1. 스레드 HTTP 서버 기동 — `/proxy/ccab` 하위에 well-known 카드(`"url":"/a2a"` 루트상대) + a2a 엔드포인트.
     base `/proxy/ccab`는 404(→ fetch_card가 well-known 관례로 폴백). a2a는 GET 405/POST 200(실 A2A 흉내).
  2. connect_agent(url="…/proxy/ccab") → 실 DB 등록.
  3. 저장 endpoint == "…/proxy/ccab/a2a" (prefix 보존! — 071 핵심). 옛 버그값 "…/a2a"가 *아님*을 대조.
  4. status online (probe가 405를 live로 봄 — 404였다면 071 P2로 dead).
  5. 저장 endpoint로 직접 JSON-RPC POST → mock 응답 도달(resolve된 경로가 실제 서비스).
  6. 생성 행 정리.

전제: DB 마이그레이션 적용됨(API 서버는 불요 — connect_agent를 in-process로 호출).
실행: uv run --project packages/api python tests/verify_071_live.py   (or: .venv/bin/python)
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
from api.agents import connect_agent  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent  # noqa: E402
from api.schemas import ConnectAgentIn  # noqa: E402

# fetch_card/probe_endpoint가 127.0.0.1 mock에 닿도록 allowlist(스펙 064 시seam, DB 무관).
net_guard._set_allowed_hosts_for_test(["127.0.0.1"])

PREFIX = "/proxy/ccab"
CARD = {
    "name": "Prefixed Proxy Agent (071)",
    "description": "프록시 path-prefix 배포 재현 — 카드가 루트상대 /a2a 발행.",
    "url": "/a2a",  # ← 루트상대(비표준). 071이 prefix 하위로 구제해야 함.
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [{"id": "s", "name": "s", "description": "d", "tags": []}],
}
MOCK_REPLY = "스펙071 prefix endpoint 도달 OK"

_fails: list[str] = []


def ck(c: bool, m: str) -> None:
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 조용히
        pass

    def _send(self, code: int, obj=None):
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
            self._send(405)  # A2A 엔드포인트 존재·GET 불가 → probe는 live로 봐야(404 아님)
        else:
            self._send(404)  # base 등 → fetch_card가 well-known 폴백

    def do_POST(self):
        if self.path == f"{PREFIX}/a2a":
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": MOCK_REPLY}],
                    "messageId": "m1",
                    "kind": "message",
                },
            })
        else:
            self._send(404)


async def _connect(url: str):
    async with SessionLocal() as s:
        out = await connect_agent(ConnectAgentIn(url=url, token=None), s)
    return out


async def _cleanup(pk) -> None:
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        if row is not None:
            await s.delete(row)
            await s.commit()


async def main() -> None:
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}{PREFIX}"
    want_endpoint = f"http://127.0.0.1:{port}{PREFIX}/a2a"
    old_bug_endpoint = f"http://127.0.0.1:{port}/a2a"  # prefix 탈락 시(옛 버그)

    pk = None
    try:
        out = await _connect(base)
        pk = out.id

        ck(out.endpoint == want_endpoint,
           f"L1 저장 endpoint가 prefix 보존 (want={want_endpoint}, got={out.endpoint})")
        ck(out.endpoint != old_bug_endpoint,
           "L2 옛 버그값(prefix 탈락 …/a2a)이 아님 — 회귀 대조")
        ck(getattr(out, "status", None) == "online",
           f"L3 probe 405를 live로 → status online (got={getattr(out, 'status', None)})")

        # L4 — 저장 endpoint가 실제 도달(resolve된 경로가 서비스). 직접 JSON-RPC POST.
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(out.endpoint, json={
                "jsonrpc": "2.0", "id": "1", "method": "message/send",
                "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}},
            })
            txt = ""
            if r.status_code == 200:
                parts = (r.json().get("result") or {}).get("parts") or []
                txt = "".join(p.get("text", "") for p in parts)
        ck(MOCK_REPLY in txt, f"L4 저장 endpoint로 POST → mock 응답 도달 (got={txt!r})")
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
    print("ALL PASS (4 — prefix 보존·회귀대조·probe live·도달)")


if __name__ == "__main__":
    asyncio.run(main())
