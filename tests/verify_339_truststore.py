"""verify_339 — 사내 CA 지원: OS 신뢰 저장소 옵트인 (스펙 339).

  V1 기본 꺼짐: env 없이 api.main import → ssl.SSLContext가 표준 stdlib 클래스(주입 안 됨).
  V2 켬: SYSTEM_TRUSTSTORE=1 → ssl.SSLContext가 truststore.SSLContext(전역 주입 성사).
  V3 무회귀: 켠 상태에서 외부 TLS 실동작 — wiki_search 도구 실호출(표준 CA 사이트가
     OS 저장소로도 검증됨을 실증. 사내 MITM 재현은 불가 — 정직 경계, 스펙 339).
실행: uv run --project packages/api python tests/verify_339_truststore.py  (외부 네트워크 필요: V3)
"""

import os
import subprocess
import sys

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


PROBE = (
    "import sys, ssl; sys.path.insert(0, 'packages/api/src');"
    "import api.main;"  # 주입 지점 통과
    "import truststore;"
    "print('truststore' if ssl.SSLContext is truststore.SSLContext else 'stdlib')"
)

WIKI = (
    "import sys, json; sys.path.insert(0, 'packages/api/src');"
    "import api.main;"  # SYSTEM_TRUSTSTORE=1이면 여기서 주입
    "from api.served_mcp import wiki_search;"
    "out = wiki_search.func('파이썬', limit=1, lang='ko');"
    "d = json.loads(out);"
    "print('WIKI-OK' if 'error' not in d else 'WIKI-ERR ' + str(d)[:120])"
)


def _run(code: str, env_extra: dict) -> str:
    env = {**os.environ, **env_extra}
    env.pop("SYSTEM_TRUSTSTORE", None) if not env_extra else None
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=_ROOT)
    return (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "(무출력)"


def main():
    base_env = {k: v for k, v in os.environ.items() if k != "SYSTEM_TRUSTSTORE"}

    # V1 — 기본 꺼짐
    r1 = subprocess.run([sys.executable, "-c", PROBE], env=base_env, capture_output=True, text=True, cwd=_ROOT)
    out1 = r1.stdout.strip().splitlines()[-1] if r1.stdout.strip() else r1.stderr[-120:]
    check(out1 == "stdlib", f"V1 기본 꺼짐 = 표준 SSLContext (got {out1})")

    # V2 — 켬(전역 주입)
    r2 = subprocess.run([sys.executable, "-c", PROBE], env={**base_env, "SYSTEM_TRUSTSTORE": "1"}, capture_output=True, text=True, cwd=_ROOT)
    out2 = r2.stdout.strip().splitlines()[-1] if r2.stdout.strip() else r2.stderr[-120:]
    check(out2 == "truststore", f"V2 SYSTEM_TRUSTSTORE=1 = truststore 주입 (got {out2})")

    # V3 — 켠 상태 외부 TLS 실동작(위키 실호출 — 무회귀)
    r3 = subprocess.run([sys.executable, "-c", WIKI], env={**base_env, "SYSTEM_TRUSTSTORE": "1"}, capture_output=True, text=True, cwd=_ROOT)
    combined = r3.stdout + r3.stderr  # httpx 로그(stderr)가 뒤섞이므로 마지막 줄이 아니라 포함으로
    check("WIKI-OK" in combined, f"V3 truststore로 위키 TLS 실동작 (tail={combined.strip()[-120:]})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY339_OK — {passed}건 전부 통과")


main()
