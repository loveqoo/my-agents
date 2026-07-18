"""verify_164 — 프로바이더 연결 테스트가 항상 "모델 미발견"이던 버그(스펙 164).

프로바이더 레벨 테스트는 빈 model_id로 _probe를 호출하는데, 기존 로직이 빈 model_id를 무조건
미발견으로 판정했다. 수정 후: 빈 model_id면 /models 목록 개수로 판정. 로컬 stub 서버로 실제 _probe 호출.
실행: cd packages/api && uv run python ../../tests/verify_164_provider_probe.py
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from api.model_registry import _probe

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


_MODELS = {"data": [{"id": "gpt-x"}, {"id": "emb-y"}]}
_EMPTY = {"data": []}


def _make_handler(payload):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # 조용히
            pass

    return H


def _serve(payload):
    srv = HTTPServer(("127.0.0.1", 0), _make_handler(payload))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


async def main() -> None:
    srv2, url2 = _serve(_MODELS)  # 모델 2개
    srv0, url0 = _serve(_EMPTY)  # 모델 0개
    try:
        # 1) 빈 model_id + 모델 2개 → "모델 2개 발견"·available(before=미발견 버그).
        r = await _probe(url2, None, "", "chat")
        check(
            r.modelAvailable is True and "2개" in r.detail,
            f"H1 빈 model_id·모델2개 → 발견 (got available={r.modelAvailable}, detail={r.detail!r})",
        )

        # 2) 빈 model_id + 빈 목록 → "목록 비어있음"·not available.
        r = await _probe(url0, None, "", "chat")
        check(
            r.modelAvailable is False and "비어있음" in r.detail,
            f"H2 빈 model_id·모델0개 → 비어있음 (got available={r.modelAvailable}, detail={r.detail!r})",
        )

        # 3) 회귀 — model_id 지정·존재 → 사용 가능.
        r = await _probe(url2, None, "gpt-x", "chat")
        check(
            r.modelAvailable is True and "사용 가능" in r.detail,
            f"H3 model_id 존재 → 사용 가능 (got {r.detail!r})",
        )

        # 4) 회귀 — model_id 지정·부재 → 미발견(정확 일치 유지).
        r = await _probe(url2, None, "no-such", "chat")
        check(
            r.modelAvailable is False and "미발견" in r.detail,
            f"H4 model_id 부재 → 미발견 (got {r.detail!r})",
        )
    finally:
        srv2.shutdown()
        srv0.shutdown()

    print("\nPASS — 0 failed" if not _fails else f"\nFAIL — {len(_fails)} failed")
    raise SystemExit(1 if _fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
