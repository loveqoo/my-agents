"""스펙 081 단위 시맨틱(비겹침 사다리 rung 1) — 전송 폴백(C) + 오프라인 안내 술어(A).

DB·실 등록 글루 없이 두 순수 동작만 격리 검증한다(resync 자가치유의 DB+fetch 글루는 라이브 rung이 잡음):

  C-1 stream POST가 404, send POST가 200(텍스트) → a2a_stream이 message/send로 1회 폴백해 텍스트 수신.
  C-2 단일-endpoint(stream·send 둘 다 404) → 폴백해도 동일 실패 → 에러 프레임(텍스트 이중방출 없음).
  C-3 stream POST가 500(404/405 아님) → 폴백 없이 즉시 에러 프레임(방어 대상 아님).
  A-1 _a2a_stream이 텍스트 한 줄 없이 에러로 끝나면 에러 SSE에 행동가능 안내 부가.
  A-2 텍스트가 먼저 온 뒤 에러면 안내 미부가(도달은 됐으므로).

실행: .venv/bin/python tests/verify_081_unit.py
"""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import a2a_client, chat, net_guard  # noqa: E402

net_guard._set_allowed_hosts_for_test(["127.0.0.1"])

_fails: list[str] = []


def ck(c: bool, m: str) -> None:
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


REPLY = "send 폴백 응답 도달"


def _make_handler(stream_status: int, send_ok: bool):
    """stream(text/event-stream Accept) POST엔 stream_status, send(application/json) POST엔
    send_ok면 200+텍스트·아니면 404. Accept 헤더로 두 메서드를 구분(같은 endpoint)."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            accept = self.headers.get("Accept", "")
            is_stream = "text/event-stream" in accept
            if is_stream:
                code = stream_status
                if code == 200:
                    payload = b"data: [DONE]\n\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # send (application/json)
            if not send_ok:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            out = json.dumps({
                "jsonrpc": "2.0", "id": body.get("id"),
                "result": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": REPLY}],
                    "messageId": "m1", "kind": "message",
                },
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    return H


async def _collect(endpoint: str):
    frames = []
    async for f in a2a_client.a2a_stream(endpoint, None, "hi", streaming=True, context_id="s1"):
        frames.append(f)
    return frames


def _run_server(handler):
    srv = HTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}/a2a"


async def test_C():
    # C-1: stream 404, send 200 → 폴백 텍스트
    srv, ep = _run_server(_make_handler(404, send_ok=True))
    try:
        frames = await _collect(ep)
    finally:
        srv.shutdown()
    texts = [f["text"] for f in frames if "text" in f]
    errs = [f["error"] for f in frames if "error" in f]
    fbs = [f for f in frames if "_fallback" in f]
    ck(REPLY in "".join(texts), f"C-1 stream404→send 폴백으로 텍스트 수신 (got={texts!r})")
    ck(not errs, f"C-1 에러 프레임 없음 (got={errs!r})")
    ck(not fbs, "C-1 _fallback 신호는 내부 소비 — 상위로 새지 않음")

    # C-2: stream 404, send 404 → 동일 실패, 에러 프레임(텍스트 없음)
    srv, ep = _run_server(_make_handler(404, send_ok=False))
    try:
        frames = await _collect(ep)
    finally:
        srv.shutdown()
    texts = [f["text"] for f in frames if "text" in f]
    errs = [f["error"] for f in frames if "error" in f]
    ck(not texts, f"C-2 단일-endpoint 404 → 텍스트 이중방출 없음 (got={texts!r})")
    ck(any("404" in e for e in errs), f"C-2 폴백도 404 → 에러 프레임 (got={errs!r})")

    # C-3: stream 500 → 폴백 없이 즉시 에러
    srv, ep = _run_server(_make_handler(500, send_ok=True))
    try:
        frames = await _collect(ep)
    finally:
        srv.shutdown()
    texts = [f["text"] for f in frames if "text" in f]
    errs = [f["error"] for f in frames if "error" in f]
    ck(not texts, f"C-3 500은 폴백 안 함 → 텍스트 없음 (got={texts!r})")
    ck(any("500" in e for e in errs), f"C-3 500 에러 프레임 그대로 (got={errs!r})")


HINT = "재동기화"


async def _drain_a2a(frames_to_yield):
    """chat._a2a_stream을 a2a_client.a2a_stream 몽키패치로 구동 — 에러 SSE 문자열을 수집."""
    async def fake_stream(endpoint, token, user_text, *, streaming=True, context_id=None):
        for f in frames_to_yield:
            yield f

    orig = a2a_client.a2a_stream
    a2a_client.a2a_stream = fake_stream
    ctx = {
        "session_id": "s1", "endpoint": "http://127.0.0.1:1/a2a", "card": {},
        "token": None, "ext_agent_id": "e1", "persist_history": False,
    }
    out = []
    try:
        async for chunk in chat._a2a_stream(ctx, "hi", None):
            out.append(chunk)
    finally:
        a2a_client.a2a_stream = orig
    return out


async def test_A():
    # A-1: 텍스트 없이 에러 → 안내 부가
    out = await _drain_a2a([{"error": "외부 에이전트 응답 오류 404"}])
    err_line = next((c for c in out if '"error"' in c), "")
    ck(HINT in err_line, f"A-1 텍스트 무방출 에러에 안내 부가 (got={err_line!r})")

    # A-2: 텍스트 먼저 온 뒤 에러 → 안내 미부가
    out = await _drain_a2a([{"text": "부분 "}, {"error": "외부 에이전트 응답 오류 500"}])
    err_line = next((c for c in out if '"error"' in c), "")
    ck(HINT not in err_line, f"A-2 부분스트림 뒤 에러엔 안내 미부가 (got={err_line!r})")


async def main():
    await test_C()
    await test_A()
    net_guard._set_allowed_hosts_for_test([])
    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (C 폴백 3 + A 안내 술어 2 = 7 체크)")


if __name__ == "__main__":
    asyncio.run(main())
