"""verify_340 — 사내 CA 파일 방식(EXTRA_CA_FILE) (스펙 340).

서버는 http 그대로 — **아웃바운드 HTTPS 검증**에 지정 CA를 추가하는 기능. 사내 MITM을 로컬로
실재현: 자가서명 CA로 임시 TLS 리스너("사내 CA 서명 외부 사이트" 대역)를 띄우고 —
  V1 기본 꺼짐: env 없이 import 후 ssl.create_default_context가 표준(패치 안 됨).
  V2 미존재 경로: EXTRA_CA_FILE 오타 → 부팅 실패(조용한 무시 금지 — "설정했는데 안 됨" 방지).
  V3 재현: EXTRA_CA_FILE **없이** 대역 사이트 GET → 인증서 검증 실패(회사 디바이스의 현 증상).
  V4 처방: EXTRA_CA_FILE=그 CA → 같은 GET 성공(증상 해소 실증).
  V5 무회귀: EXTRA_CA_FILE 켠 채 위키(표준 CA) GET 성공 — 교체가 아니라 **추가**임을 실증.
실행: uv run --project packages/api python tests/verify_340_extra_ca.py  (V5는 외부 네트워크)
"""

import os
import subprocess
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


PORT = 8443

SERVER = f"""
import http.server, ssl, sys
httpd = http.server.HTTPServer(("127.0.0.1", {PORT}), http.server.SimpleHTTPRequestHandler)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(certfile=sys.argv[1], keyfile=sys.argv[2])
httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
print("READY", flush=True)
httpd.serve_forever()
"""

CLIENT = f"""
import sys
sys.path.insert(0, 'packages/api/src')
import api.main  # EXTRA_CA_FILE 있으면 여기서 패치
import httpx
try:
    r = httpx.get("https://127.0.0.1:{PORT}/", timeout=10)
    print("GET-OK", r.status_code)
except Exception as exc:
    print("GET-ERR", type(exc).__name__, str(exc)[:80])
"""

WIKI = """
import sys
sys.path.insert(0, 'packages/api/src')
import api.main
import httpx
try:
    r = httpx.get("https://ko.wikipedia.org/w/api.php?action=query&format=json&meta=siteinfo", timeout=15)
    # 상태코드와 무관 — HTTP 응답을 받았다는 것 자체가 TLS 검증 통과(403=위키 UA 정책, 앱 계층).
    print("WIKI-OK", r.status_code)
except Exception as exc:
    print("WIKI-ERR", type(exc).__name__, str(exc)[:80])
"""

PROBE = (
    "import sys, ssl; sys.path.insert(0, 'packages/api/src');"
    "import api.main;"
    "print('patched' if ssl.create_default_context.__name__ == '_create_ctx_with_extra_ca' else 'stdlib')"
)


def _run(code: str, env_extra: dict) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("EXTRA_CA_FILE", "SYSTEM_TRUSTSTORE")}
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=_ROOT)
    out = (r.stdout + r.stderr).strip()
    return out


def main():
    with tempfile.TemporaryDirectory() as td:
        cert, key = os.path.join(td, "ca.pem"), os.path.join(td, "ca.key")
        # 자가서명 인증서(SAN=127.0.0.1) — "사내 CA 서명 외부 사이트" 대역.
        gen = subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", key, "-out", cert, "-days", "1",
             "-subj", "/CN=127.0.0.1",
             "-addext", "subjectAltName=IP:127.0.0.1"],
            capture_output=True, text=True,
        )
        assert gen.returncode == 0, f"openssl 실패: {gen.stderr[:200]}"

        # V1 — 기본 꺼짐
        out1 = _run(PROBE, {})
        check(out1.splitlines()[-1] == "stdlib", f"V1 기본 꺼짐 = 표준 create_default_context (got {out1[-60:]})")

        # V2 — 미존재 경로 = 부팅 실패(조용한 무시 금지)
        out2 = _run(PROBE, {"EXTRA_CA_FILE": os.path.join(td, "no-such.pem")})
        check("EXTRA_CA_FILE 경로에 파일이 없습니다" in out2, f"V2 오타 경로 → 부팅 실패 (got {out2[-80:]})")

        # 대역 TLS 리스너 기동
        srv = subprocess.Popen([sys.executable, "-c", SERVER, cert, key], stdout=subprocess.PIPE, text=True)
        try:
            line = srv.stdout.readline()
            assert "READY" in line, f"대역 서버 기동 실패: {line}"
            time.sleep(0.3)

            # V3 — 설정 없이 = 검증 실패(회사 디바이스 현 증상 재현)
            out3 = _run(CLIENT, {})
            check("GET-ERR" in out3 and ("CERTIFICATE_VERIFY_FAILED" in out3 or "SSL" in out3),
                  f"V3 미설정 → 인증서 검증 실패 재현 (got {out3.splitlines()[-1][:80]})")

            # V4 — EXTRA_CA_FILE = 성공(처방 실증)
            out4 = _run(CLIENT, {"EXTRA_CA_FILE": cert})
            check("GET-OK" in out4, f"V4 EXTRA_CA_FILE 지정 → 같은 요청 성공 (got {out4.splitlines()[-1][:80]})")
        finally:
            srv.terminate()
            srv.wait(timeout=5)

        # V5 — 무회귀: 켠 채 표준 CA 사이트(위키)도 성공 = 교체가 아니라 추가
        out5 = _run(WIKI, {"EXTRA_CA_FILE": cert})
        check("WIKI-OK" in out5, f"V5 켠 채 표준 사이트 무회귀(추가지 교체 아님) (got {out5.splitlines()[-1][:80]})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY340_OK — {passed}건 전부 통과")


main()
