"""스펙 063 단위(시맨틱) — 호출 경계 정규화·_norm_endpoint·마이그레이션 선별 (DB 불요).

비겹침 사다리의 단위 rung(메모리 verification-ladder): 순수 로직만 떼어 본다.
  U1  normalize_http_url 시맨틱(스킴없음→http전치, //→http전치, 절대 유지, 비-http/빈값→ValueError)
  U2  보안 불변: 127.0.0.1은 정규화 후에도 guard_url이 여전히 차단(정규화가 가드 우회 아님)
  U3  D1: a2a_stream가 scheme-less endpoint에 "절대 URL" 에러 대신 조치 가능한 SSRF 메시지를 냄
  U4  _norm_endpoint(빌더): 스킴없음→http, 절대 유지, 비-http→raw 보존(등록 500 방지), None/공백→None
  U5  마이그레이션 _needs_norm 선별: 스킴없음→후보, 절대(대/소문자)→제외(멱등), None/공백→제외

실행: uv run --project packages/api python tests/verify_063_unit.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, ROOT)

# 결정성: 보안 불변(U2/U3)은 주변 환경/DB 상태에 의존하면 안 된다(127.0.0.1이 어딘가서
# 허용돼 있으면 가드가 통과해 거짓 실패). 빈 허용목록을 강제해 "127.0.0.1은 정규화 후에도
# 차단"을 환경 무관하게 검증한다. 스펙 064: allowlist 소스가 env→DB 스냅샷으로 바뀌어,
# 시seam(_set_allowed_hosts_for_test)으로 스냅샷을 비워 고정한다(만료=inf → refresh no-op).
from api import a2a_client  # noqa: E402
from api.agents import _norm_endpoint  # noqa: E402
from api.net_guard import (  # noqa: E402
    SsrfBlocked,
    _set_allowed_hosts_for_test,
    guard_url,
    normalize_http_url,
)

_set_allowed_hosts_for_test([])
from tests.migrate_063_normalize_endpoints import _needs_norm  # noqa: E402

_fails: list[str] = []


def ck(c: bool, m: str) -> None:
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


# U1 — normalize_http_url 시맨틱
ck(normalize_http_url("example.com:9000/a2a") == "http://example.com:9000/a2a", "U1 스킴없음 host:port → http 전치")
ck(normalize_http_url("//example.com/a2a") == "http://example.com/a2a", "U1 스킴-상대 // → http 전치")
ck(normalize_http_url("https://x.com") == "https://x.com", "U1 이미 절대 → 유지(멱등)")
for bad in ("ftp://x.com", "", "   "):
    try:
        normalize_http_url(bad)
        ck(False, f"U1 {bad!r} 거부 기대했으나 통과")
    except ValueError:
        ck(True, f"U1 {bad!r} → ValueError(거부)")

# U1b — 적대 회귀(codex [P1]): colon-form userinfo가 공인 호스트로 둔갑하는 SSRF 벡터 거부.
# `mailto:user@example.com` 류가 `http://mailto:user@example.com`로 전치되면 host=example.com(공인)이
# 돼 비-http로 거부되던 값이 가드를 통과한다 → normalize 단계에서 ValueError로 막아야 한다.
for vec in (
    "mailto:user@example.com/a2a",
    "gopher:user@evil.example:80/a2a",
    "javascript:foo@evil.example/a2a",
    "evil.com@127.0.0.1/",          # userinfo로 실제 host를 127.0.0.1로 숨김
    "example.com:80@127.0.0.1:81/",  # 포트까지 섞은 userinfo 트릭
    "user:pass@example.com",         # 평범한 userinfo도 거부(정상 A2A엔 없음)
):
    try:
        normalize_http_url(vec)
        ck(False, f"U1b SSRF 벡터 {vec!r} 통과(거부 기대!)")
    except ValueError:
        ck(True, f"U1b SSRF 벡터 {vec!r} → ValueError(거부)")

# U1c — 적대 회귀(codex 후속): percent-encoded '@'(%40)는 normalize를 통과할 수 있으나
# hostname이 literal '%40' 포함 문자열로 남아 호출 경계의 guard_url이 resolve 실패로 차단한다
# (방어 다중화: normalize는 절대화만, 사설/둔갑 판정은 guard). 결합 경로가 막는지 고정한다.
for vec in ("evil.com%40127.0.0.1", "user%3apass%40example.com/a2a"):
    try:
        nrm = normalize_http_url(vec)
    except ValueError:
        ck(True, f"U1c encoded-@ {vec!r} → normalize 단계 ValueError(거부)")
        continue
    try:
        guard_url(nrm)
        ck(False, f"U1c encoded-@ {vec!r} normalize+guard 모두 통과(둔갑 우회!)")
    except SsrfBlocked:
        ck(True, f"U1c encoded-@ {vec!r} → guard_url 차단(둔갑 실패)")

# U2 — 보안 불변: 정규화 후에도 사설/루프백 차단
n = normalize_http_url("127.0.0.1:8000/a2a")
ck(n == "http://127.0.0.1:8000/a2a", "U2 127.0.0.1 절대화")
try:
    guard_url(n)
    ck(False, "U2 127.0.0.1 정규화 후 guard 통과(불변 깨짐!)")
except SsrfBlocked:
    ck(True, "U2 127.0.0.1 정규화 후에도 guard_url 차단(보안 불변 유지)")


# U3 — D1: a2a_stream scheme-less → "절대 URL" 아님
async def _first_frame(ep: str) -> dict | None:
    async for f in a2a_client.a2a_stream(ep, None, "hi", streaming=False):
        return f
    return None


f = asyncio.run(_first_frame("127.0.0.1:8000/a2a"))
err = (f or {}).get("error", "")
ck("절대 URL" not in err, f"U3 scheme-less endpoint가 '절대 URL' 에러 아님 → {err!r}")
ck("차단" in err or "127" in err, f"U3 대신 조치 가능한 차단 메시지: {err[:60]!r}…")

# U4 — _norm_endpoint(빌더)
ck(_norm_endpoint("example.com:9000") == "http://example.com:9000", "U4 _norm_endpoint 스킴없음→http")
ck(_norm_endpoint("https://x.com/a") == "https://x.com/a", "U4 _norm_endpoint 절대 유지")
ck(_norm_endpoint("ftp://x.com") == "ftp://x.com", "U4 _norm_endpoint 비-http→raw 보존(등록 500 방지)")
ck(_norm_endpoint(None) is None, "U4 _norm_endpoint None→None")
ck(_norm_endpoint("  ") is None, "U4 _norm_endpoint 공백→None")

# U5 — 마이그레이션 선별
ck(_needs_norm("example.com:9000") is True, "U5 _needs_norm 스킴없음→후보")
ck(_needs_norm("http://x.com") is False, "U5 _needs_norm 절대→제외(멱등)")
ck(_needs_norm("HTTPS://x.com") is False, "U5 _needs_norm 대문자 스킴→제외")
ck(_needs_norm(None) is False, "U5 _needs_norm None→제외")
ck(_needs_norm("  ") is False, "U5 _needs_norm 공백→제외")

print()
if _fails:
    print(f"063 unit: {len(_fails)} FAIL")
    raise SystemExit(1)
print("063 unit: PASS")
