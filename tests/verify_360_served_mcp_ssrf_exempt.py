"""스펙 360 검증 — 자체 served MCP는 SSRF 가드 예외(리셋 후 web-fetch 502 봉합).

데이터 리셋으로 allowed_hosts에서 127.0.0.1이 빠지면, 우리 자체 served MCP(플랫폼이 자기 자신에 붙는
127.0.0.1 서빙)가 SSRF 가드에 막혀 연결 실패(502)한다. 자체 served 연결은 SSRF 대상이 아니므로 예외한다.
예외는 의도 신호(레지스트리 이름 + served_url 정확 일치)라 사용자가 우회 못 한다.

단언(순수 단위 — 가드 스냅샷을 비워 127.0.0.1을 '미허용' 상태로 두고 판정):
  E1. is_own_served_url 진리표 — 정품 served만 True, 스푸핑(다른 이름·다른 url)은 False.
  E2. 127.0.0.1 미허용에도 served MCP는 mcp_connection이 conn 반환(예외 작동).
  E3. 무회귀 — 비-served 127.0.0.1 URL·외부 사설은 여전히 차단(None); allowlist에 있으면 통과.

실행: .venv/bin/python tests/verify_360_served_mcp_ssrf_exempt.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import net_guard  # noqa: E402
from api.runtime import mcp_connection  # noqa: E402
from api.served_mcp import SERVED_MCP_TOOLS, is_own_served_url, served_url  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _http(name: str, url: str) -> dict:
    return {"name": name, "url": url, "transport": "streamable_http"}


def main() -> None:
    wf = "web-fetch"
    wf_url = served_url(wf)  # http://127.0.0.1:8000/_served/mcp/web-fetch/
    assert wf in SERVED_MCP_TOOLS, "전제: web-fetch가 served 레지스트리에 있어야"

    # ── E1: is_own_served_url 진리표 ──────────────────────────────────────────
    check(is_own_served_url(wf, wf_url) is True, "E1 정품 served (web-fetch, served_url) → True")
    check(is_own_served_url("calc-tools", served_url("calc-tools")) is True, "E1 calc-tools 정품 → True")
    # 스푸핑: 미등록 이름에 served URL 박기 → name 미등록이라 False(사용자 우회 차단)
    check(is_own_served_url("myserver", wf_url) is False, "E1 스푸핑(다른 이름 + served url) → False")
    # 스푸핑: 정품 이름인데 url이 다름(임의 내부) → 정확 일치 아니라 False
    check(is_own_served_url(wf, "http://127.0.0.1:8000/internal/admin") is False, "E1 정품 이름 + 다른 url → False")
    check(is_own_served_url(wf, "http://evil.example/_served/mcp/web-fetch/") is False, "E1 정품 이름 + 외부호스트 url → False")
    check(is_own_served_url(None, wf_url) is False, "E1 이름 없음 → False")
    # 트레일링 슬래시 정확성(served_url은 끝 슬래시 필수)
    check(is_own_served_url(wf, wf_url.rstrip("/")) is False, "E1 트레일링 슬래시 없으면 불일치 → False")

    # ── 가드 스냅샷을 비워 127.0.0.1을 '미허용'으로(리셋 후 상태 모사) ──────────
    net_guard._set_allowed_hosts_for_test([])  # allowlist 비움 → 루프백 전부 차단

    # E2: 미허용에도 served MCP는 연결 dict 반환(예외 작동)
    conn = mcp_connection(_http(wf, wf_url))
    check(conn is not None and conn.get("url") == wf_url, "E2 127.0.0.1 미허용에도 served MCP 연결(502 봉합)")

    # E3 무회귀: 비-served 127.0.0.1 URL은 여전히 차단(None)
    blocked = mcp_connection(_http("myserver", "http://127.0.0.1:8000/_served/mcp/web-fetch/"))
    check(blocked is None, "E3 비-served(다른 이름)로 127.0.0.1 → 여전히 차단(우회 불가)")
    blocked2 = mcp_connection(_http("evilsrv", "http://127.0.0.1:9999/x"))
    check(blocked2 is None, "E3 임의 루프백 URL → 차단")
    # 외부 사설대역도 차단(예: 169.254 링크로컬)
    blocked3 = mcp_connection(_http("meta", "http://169.254.169.254/latest/meta-data"))
    check(blocked3 is None, "E3 링크로컬 메타데이터 → 차단(SSRF 무회귀)")

    # E3: allowlist에 127.0.0.1 있으면 비-served도 통과(dev mock 무회귀)
    net_guard._set_allowed_hosts_for_test(["127.0.0.1"])
    allowed = mcp_connection(_http("mymock", "http://127.0.0.1:8000/mock/x"))
    check(allowed is not None, "E3 allowlist에 127.0.0.1 → 비-served도 통과(dev mock 무회귀)")

    net_guard._set_allowed_hosts_for_test([])  # 정리

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_360)")


if __name__ == "__main__":
    main()
