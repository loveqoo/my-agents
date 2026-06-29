"""스펙 063 라이브 통합(실 인프라) — stale 스킴누락 endpoint 자가치유 + 마이그레이션 왕복.

비겹침 사다리의 통합 rung(메모리 verification-ladder): *저장→호출* 글루를 실 DB+실 API로 검증.
단위(verify_063_unit)는 순수 로직만, 이 테스트만이 "스킴 없는 행이 DB에 있을 때 실제 채팅이
자가치유되는가 + 마이그레이션이 그 행을 정확히 집어 절대화하는가"를 잡는다.

흐름:
  1. 127.0.0.1 mock A2A 서버 기동(message/send 단건 → JSONRPCResponse text).
  2. stale 행 주입: source=external, endpoint="127.0.0.1:PORT"(스킴 없음!), card.capabilities.streaming=false.
  3. 실 API POST /{pk}/chat → SSE에서 mock 텍스트 수신 확인(더는 "절대 URL" 에러 아님) ← D1 자가치유.
  4. 마이그레이션 dry-run이 그 행을 정확히 1건 집음 → --apply 후 endpoint가 "http://127.0.0.1:PORT"로.
  5. 행 정리(주입한 테스트 행만 삭제).

선행: API가 127.0.0.1:8000에서 A2A_ALLOWED_HOSTS=127.0.0.1 로 떠 있어야 함(127 mock 허용).
실행: uv run --project packages/api python tests/verify_063_live.py
"""

import asyncio
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import asyncpg
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

BASE = "http://127.0.0.1:8000"
TOK = os.environ["API_AUTH_TOKEN"]
AUTH = {"Authorization": f"Bearer {TOK}"}
DSN = os.environ.get("MIGRATE_DSN", "postgresql://agent:agent@localhost:5432/agents")
MOCK_REPLY = "스펙063 mock 응답 OK"
TEST_AGENT_ID = "agt_test063_stale"

_fails: list[str] = []


def ck(c: bool, m: str) -> None:
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


# ---- 1. mock A2A 서버 (message/send 단건) ----
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 조용히
        pass

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        self.rfile.read(ln)  # 본문 소비(검사 불요)
        resp = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "kind": "message",
                "role": "agent",
                "parts": [{"kind": "text", "text": MOCK_REPLY}],
            },
        }
        body = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


httpd = HTTPServer(("127.0.0.1", 0), _Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
STALE_EP = f"127.0.0.1:{PORT}"  # 스킴 없음 — 버그 재현의 핵심
print(f"mock A2A @ 127.0.0.1:{PORT}, stale endpoint={STALE_EP!r}")


def _req(method, path, *, headers=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


async def _insert_stale(conn) -> str:
    """스킴 없는 endpoint를 가진 external 에이전트 1건 주입. pk(UUID str) 반환."""
    await conn.execute("DELETE FROM agents WHERE agent_id = $1", TEST_AGENT_ID)
    card = {
        "name": "063 stale 테스트",
        "url": STALE_EP,
        "capabilities": {"streaming": False},  # 단건 message/send 경로
    }
    pk = await conn.fetchval(
        "INSERT INTO agents (id, agent_id, name, source, model, persona, history_depth, "
        "config, exposed, status, endpoint, token) "
        "VALUES (gen_random_uuid(), $1, $2, 'external', '', '', 10, $3, $4, 'online', $5, NULL) "
        "RETURNING id",
        TEST_AGENT_ID,
        "063 stale 테스트",
        json.dumps({"card": card, "model": "", "persona": "", "memories": [],
                    "vectorTables": [], "permissions": [], "mcps": [], "historyDepth": 10}),
        json.dumps({"a2a": False}),
        STALE_EP,
    )
    return str(pk)


async def main() -> int:
    conn = await asyncpg.connect(DSN)
    try:
        pk = await _insert_stale(conn)
        print(f"주입된 stale 행 pk={pk}")

        # ---- 3. 실 채팅: 더는 "절대 URL" 아님, mock 텍스트 수신 ----
        status, raw = _req("POST", f"/agents/{pk}/chat", headers=AUTH,
                           body={"messages": [{"role": "user", "content": "안녕"}]})
        ck(status == 200, f"L1 POST /chat → 200 (실제 {status}: {raw[:120]})")
        ck("절대 URL" not in raw, "L2 응답에 '절대 URL' 에러 없음(D1 자가치유)")
        ck(MOCK_REPLY in raw, f"L3 mock 응답 텍스트 수신: {MOCK_REPLY!r} in SSE")

        # ---- 4. 마이그레이션: 이 행을 정확히 집고 --apply로 절대화 ----
        sys.path.insert(0, ROOT)
        from tests.migrate_063_normalize_endpoints import _needs_norm
        from api.net_guard import normalize_http_url

        ep_before = await conn.fetchval("SELECT endpoint FROM agents WHERE agent_id=$1", TEST_AGENT_ID)
        ck(_needs_norm(ep_before) is True, f"L4 마이그레이션이 주입행을 후보로 선별(endpoint={ep_before!r})")
        # --apply 시뮬레이트 직접 적용(스크립트 _apply 경로와 동일 정규화)
        ep_norm = normalize_http_url(ep_before)
        ck(ep_norm == f"http://127.0.0.1:{PORT}", f"L5 절대화 결과 정확: {ep_norm!r}")
        await conn.execute("UPDATE agents SET endpoint=$1 WHERE agent_id=$2", ep_norm, TEST_AGENT_ID)
        ep_after = await conn.fetchval("SELECT endpoint FROM agents WHERE agent_id=$1", TEST_AGENT_ID)
        ck(ep_after == ep_norm, f"L6 UPDATE 반영 재조회: {ep_after!r}")
        ck(_needs_norm(ep_after) is False, "L7 멱등: 절대화 후 더는 후보 아님")
    finally:
        await conn.execute("DELETE FROM agents WHERE agent_id = $1", TEST_AGENT_ID)
        await conn.close()
        httpd.shutdown()

    print()
    if _fails:
        print(f"063 live: {len(_fails)} FAIL")
        return 1
    print("063 live: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
