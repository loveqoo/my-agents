"""스펙 060 검증 — A2A 서비스 url 관대 정규화(순수 단위, DB·서버 불필요).

normalize_http_url이 모드1(스킴 없는/상대 url)을 등록 시점에 절대 http(s)로 정규화하고, 보안 불변
(정규화된 사설 url은 여전히 guard_url이 차단)을 깨지 않는지 단언한다. learning 063 가족 —
가드는 *막을 때 말하는 법*, 여기 060은 *늦게 모호하게 막던 것을 일찍 절대화*.

검증(완료조건 C1~C5):
  C1. 스킴 없는 host:port/path → http:// 전치(절대화).
  C2. `/path` 상대 + base → base origin으로 resolve(절대 http(s)).
  C3. 이미 절대 https:// → 불변.
  C4. 정규화 불가(ftp://·빈 값·`://`·base 없는 상대) → ValueError(메시지에 http(s) 언급).
  C5. 보안 불변 — 정규화된 사설/루프백 url도 guard_url(allowlist 없음)이 SsrfBlocked로 차단.
  추가. 스킴-상대(//host)·IPv6·포트-only 엣지(codex 적대 점검축 선반영).

실행: uv run python tests/verify_060_url_normalization.py   (or: .venv/bin/python)
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

# C5는 allowlist가 비어야 사설 차단을 단언할 수 있다 — 명시적으로 비운다(상속 환경 무시).
os.environ["A2A_ALLOWED_HOSTS"] = ""

from api.net_guard import SsrfBlocked, guard_url, normalize_http_url  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def expect_value(raw, expected, *, base=None):
    try:
        got = normalize_http_url(raw, base=base)
    except ValueError as exc:
        check(False, f"normalize({raw!r}, base={base!r}) → 예외 {exc} (기대 {expected!r})")
        return
    check(got == expected, f"normalize({raw!r}, base={base!r}) = {got!r} (기대 {expected!r})")


def expect_error(raw, *, base=None, must_mention="http"):
    try:
        got = normalize_http_url(raw, base=base)
        check(False, f"normalize({raw!r}, base={base!r}) = {got!r} (기대 ValueError)")
    except ValueError as exc:
        check(must_mention in str(exc), f"normalize({raw!r}) ValueError에 {must_mention!r} 포함: {exc}")


# C1 — 스킴 없는 host:port[/path] → http:// 전치
expect_value("127.0.0.1:9000/a2a", "http://127.0.0.1:9000/a2a")
expect_value("example.com/agents/x/a2a", "http://example.com/agents/x/a2a")
expect_value("localhost:8000", "http://localhost:8000")

# C2 — `/path` 상대 + base → resolve
expect_value("/agents/x/a2a", "http://127.0.0.1:8000/agents/x/a2a", base="http://127.0.0.1:8000/foo")
expect_value("/a2a", "https://host.example/a2a", base="https://host.example/.well-known/agent-card.json")

# C3 — 이미 절대 → 불변
expect_value("https://api.acme.com/a2a", "https://api.acme.com/a2a")
expect_value("http://127.0.0.1:8000/_remote/a2a", "http://127.0.0.1:8000/_remote/a2a")

# C4 — 정규화 불가
expect_error("")
expect_error("   ")
expect_error("ftp://host/x")        # 비-http 스킴
expect_error("://host/x")           # 스킴 없는 `://`
expect_error("/relative/no/base")   # base 없는 상대경로

# 엣지(codex 적대 점검축) — 스킴-상대·IPv6·포트-only
expect_value("//host.example/a2a", "http://host.example/a2a")          # 스킴-상대 → http
expect_value("[::1]:8000/a2a", "http://[::1]:8000/a2a")                 # IPv6 리터럴
expect_error(":8000/a2a")                                              # 포트-only(호스트 없음)

# C5 — 보안 불변: 정규화된 사설/루프백도 guard_url(allowlist 없음)이 차단
for raw in ("127.0.0.1:9000/a2a", "10.0.0.5:80/x", "192.168.1.2/a2a", "[::1]:8000/a2a"):
    normalized = normalize_http_url(raw)
    try:
        guard_url(normalized)
        check(False, f"guard_url({normalized!r}) 통과 — 사설 대역인데 차단 안 됨(보안 불변 위반!)")
    except SsrfBlocked:
        check(True, f"guard_url({normalized!r}) → SsrfBlocked (정규화가 가드를 우회 안 함)")

print()
if _fails:
    print(f"FAIL — {len(_fails)}건")
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("ALL PASS — VERIFY060_OK")
