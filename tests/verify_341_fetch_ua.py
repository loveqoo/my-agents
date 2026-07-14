"""verify_341 — web-fetch UA env 오버라이드 (스펙 341).

회사 디바이스 SASE 게이트웨이가 특정 UA만 통과 → 소스 하드코딩 대신 `WEB_FETCH_UA` env.
  V1 기본값 유지: env 없으면 기존 UA(일반 배포 무회귀).
  V2 오버라이드: WEB_FETCH_UA=… → _fetch_ua()가 그 값.
  V3 **실제 전송 헤더**: 로컬 에코 서버로 _wiki_get을 태워 서버가 관측한 User-Agent가 오버라이드
     값인지 확인(자가선언 아님 — 와이어에서 봄).
  V4 SSRF 무회귀: 그 로컬(=위키 밖) 호스트 응답은 호스트 재검증에서 차단됨(가드 유지).
  V5 .env 파일만으로 적용(셸 env 없이 — 회사 디바이스 시나리오, 340 후속 버그의 동형 핀).
  V6 실호출 무회귀: 오버라이드(curl UA)로 위키 실검색 성공(위키가 curl UA를 막지 않음 — 처방 유효).
  V7 프로토콜: 기본 클라이언트가 이미 HTTP/1.1(리포트의 http1/http2 강제는 무동작 — 기각 근거 핀).
실행: uv run --project packages/api python tests/verify_341_fetch_ua.py   (V6·V7은 외부 네트워크)
"""

import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails: list[str] = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


_seen_ua: list[str] = []


class _Echo(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        _seen_ua.append(self.headers.get("User-Agent", ""))
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 조용히
        pass


def main():
    os.environ.pop("WEB_FETCH_UA", None)
    from api import served_mcp as sm

    # V1 — 기본값 유지
    check(sm._fetch_ua() == sm._FETCH_UA_DEFAULT, f"V1 env 없음 → 기본 UA 유지 ({sm._fetch_ua()!r})")

    # V2 — 오버라이드
    os.environ["WEB_FETCH_UA"] = "curl/8.7.1"
    check(sm._fetch_ua() == "curl/8.7.1", f"V2 WEB_FETCH_UA 반영 ({sm._fetch_ua()!r})")

    # V3·V4 — 로컬 에코 서버로 실제 전송 헤더 관측 + 위키 밖 호스트 차단
    srv = HTTPServer(("127.0.0.1", 0), _Echo)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        res = sm._wiki_get(f"http://127.0.0.1:{port}/w/api.php", {"action": "query"})
    finally:
        srv.shutdown()
    check(_seen_ua and _seen_ua[-1] == "curl/8.7.1",
          f"V3 와이어에서 관측한 User-Agent = 오버라이드 값 (got {_seen_ua[-1:]!r})")
    check("error" in res and "비허용 호스트" in res["error"],
          f"V4 위키 밖 호스트 = 차단 유지(SSRF 가드 무회귀) (got {str(res)[:60]})")

    # V5 — .env 파일만으로 적용(셸 env 없이)
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, ".env"), "w") as f:
            f.write("WEB_FETCH_UA=curl/9.9.9-dotenv\n")
        code = (
            f"import sys; sys.path.insert(0, {os.path.join(_ROOT, 'packages', 'api', 'src')!r});"
            "import api.main;"  # db.py의 load_dotenv 경유(스펙 342로 _ca_boot 제거 후에도 유지 — 이 줄이 그 핀)
            "from api.served_mcp import _fetch_ua; print('UA=' + _fetch_ua())"
        )
        env5 = {k: v for k, v in os.environ.items() if k != "WEB_FETCH_UA"}
        r5 = subprocess.run([sys.executable, "-c", code], env=env5, capture_output=True, text=True, cwd=td)
        out5 = (r5.stdout + r5.stderr).strip()
    check("UA=curl/9.9.9-dotenv" in out5, f"V5 .env 파일만으로 적용 (tail={out5[-70:]!r})")

    # V6 — 오버라이드(curl UA)로 위키 실검색 성공(처방 유효 — 위키가 curl UA를 막지 않음)
    import json
    d = json.loads(sm.wiki_search.func("파이썬", limit=1, lang="ko"))
    check("error" not in d, f"V6 curl UA로 위키 실검색 성공 (got {str(d)[:70]})")

    # V7 — 기본 클라이언트가 이미 HTTP/1.1(리포트의 http1/http2 강제 = 무동작)
    import httpx
    r7 = httpx.get("https://ko.wikipedia.org/w/api.php",
                   params={"action": "query", "format": "json", "meta": "siteinfo"},
                   headers={"User-Agent": sm._FETCH_UA_DEFAULT}, timeout=15)
    check(r7.http_version == "HTTP/1.1", f"V7 httpx 기본 = HTTP/1.1(http1 강제 무의미) (got {r7.http_version})")

    os.environ.pop("WEB_FETCH_UA", None)
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY341_OK — {passed}건 전부 통과")


main()
