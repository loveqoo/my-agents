"""스펙 064 단위(시맨틱) 검증 — DB 없이 결정적으로 도는 부분만.

대상(스펙 064 §5 단위 rung):
  N. normalize_allowed_host — 정확 host만(빈값·공백·`*`·CIDR·스킴·콤마·`@`·포트 거부;
     호스트명 lower 정규화; IPv4/IPv6 리터럴 canonical 수용).
  C. 캐시 시맨틱 — _set_allowed_hosts_for_test 고정(만료=inf)·refresh 디바운스 no-op·
     invalidate가 만료를 0으로·guard_url이 스냅샷을 정확매칭(정규화 동형).

라이브(DB 시드·무재시작 반영·멀티워커 수렴)는 verify_064_live.py(통합 rung)에서 다룬다.

실행: .venv/bin/python tests/verify_064_unit.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import net_guard  # noqa: E402
from api.net_guard import (  # noqa: E402
    SsrfBlocked,
    _parse_ttl,
    _set_allowed_hosts_for_test,
    guard_url,
    invalidate_allowed_hosts_cache,
    normalize_allowed_host,
    refresh_allowed_hosts,
)

_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    print(f"  {'ok ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


def expect_reject(raw, why: str) -> None:
    try:
        out = normalize_allowed_host(raw)
        check(False, f"N reject {raw!r} ({why}) — 통과해버림 → {out!r}")
    except ValueError:
        check(True, f"N reject {raw!r} ({why})")


def expect_accept(raw, expected: str) -> None:
    try:
        out = normalize_allowed_host(raw)
        check(out == expected, f"N accept {raw!r} → {out!r} (기대 {expected!r})")
    except ValueError as exc:
        check(False, f"N accept {raw!r} 기대했으나 거부: {exc}")


print("[N] normalize_allowed_host — 정확 host만(파괴적 노브 바닥, learning 037/066)")
# 거부 벡터 — allow-all 둔갑/우회.
expect_reject("", "빈값")
expect_reject("   ", "공백만")
expect_reject("a b", "내부 공백")
expect_reject("*", "와일드카드")
expect_reject("*.example.com", "서브도메인 와일드카드")
expect_reject("10.0.0.0/8", "CIDR(경로 슬래시)")
expect_reject("http://host", "스킴")
expect_reject("host,other", "콤마(다중 우회)")
expect_reject("user@host", "userinfo(@ 둔갑, learning 066)")
expect_reject("host:8000", "포트")
expect_reject("ho!st", "허용되지 않는 문자")
# 적대 회귀(codex challenge 064): 미지정 주소는 단일 타깃이 아니라 와일드카드 바인드 →
# allowlist에 들면 guard_url이 _ip_is_blocked 전에 통과(로컬 리스너 노출). 정규화서 거부.
expect_reject("0.0.0.0", "미지정 IPv4(allow-local 둔갑)")
expect_reject("::", "미지정 IPv6(allow-local 둔갑)")
expect_reject("[::]", "미지정 IPv6 대괄호형")
# 적대 회귀(codex challenge 064): 과길이 host는 DB String(255)서 DataError→500. 정규화서 422.
expect_reject("a" * 254, "과길이(>253자) — 500 대신 거부")
# 수용 벡터 — 정규화 동형.
expect_accept("Example.COM", "example.com")  # 호스트명 lower
expect_accept("agent.internal", "agent.internal")
expect_accept("127.0.0.1", "127.0.0.1")  # IPv4 리터럴
expect_accept("[::1]", "::1")  # IPv6 대괄호 벗기고 canonical
expect_accept("::FFFF:127.0.0.1", "::ffff:127.0.0.1")  # IPv6 canonical lower
expect_accept(" localhost ", "localhost")  # 양끝 공백 strip

print("\n[T] _parse_ttl — 잘못된 TTL이 부팅 크래시·수렴 차단을 못 하게 [0,300] 클램프")
check(_parse_ttl(None) == 10.0, "T1 미설정 → 기본 10s")
check(_parse_ttl("30") == 30.0, "T2 정상값 보존")
check(_parse_ttl("oops") == 10.0, "T3 오타 → 크래시 대신 기본 10s")
check(_parse_ttl("inf") == 10.0, "T4 inf(비유한) → 기본 10s(제거가 영원히 안 반영되는 것 방지)")
check(_parse_ttl("-5") == 10.0, "T5 음수 → 기본 10s")
check(_parse_ttl("99999") == 300.0, "T6 과도값 → 상한 300s")

print("\n[C] 캐시 시맨틱 — 스냅샷 고정·디바운스·무효화·guard 정확매칭")


async def _cache_checks() -> None:
    # 시seam: 스냅샷 고정(만료=inf). guard_url이 사설대역이라도 스냅샷 host는 통과.
    _set_allowed_hosts_for_test(["127.0.0.1", "Agent.Internal"])
    check(net_guard._allowed_hosts() == {"127.0.0.1", "agent.internal"},
          "C1 시seam이 normalize 거쳐 lower 고정")
    check(guard_url("http://127.0.0.1:8000/x") is None, "C2 스냅샷 host(127.0.0.1) 통과")
    # 매칭은 guard_url의 parsed.hostname.lower()와 동형 — 대문자 입력도 통과.
    check(guard_url("http://AGENT.INTERNAL/a2a") is None, "C2 대문자 host도 lower 매칭 통과")

    # 디바운스: 만료=inf라 refresh(force=False)는 DB를 안 치고 no-op(스냅샷 유지).
    await refresh_allowed_hosts(force=False)
    check(net_guard._allowed_hosts() == {"127.0.0.1", "agent.internal"},
          "C3 만료 전 refresh는 no-op(디바운스, DB 미조회)")

    # 스냅샷 밖 사설은 차단.
    try:
        guard_url("http://10.0.0.5/x")
        check(False, "C4 스냅샷 밖 사설(10.0.0.5) — 통과해버림")
    except SsrfBlocked:
        check(True, "C4 스냅샷 밖 사설(10.0.0.5) 차단")

    # 무효화: 만료를 0으로 → 다음 refresh는 DB를 조회(여기선 DB 없을 수 있어 결과는 미검증,
    # 만료 플래그만 단언). monotonic now>0 이므로 0<now → 만료 상태.
    invalidate_allowed_hosts_cache()
    import time as _t
    check(net_guard._SNAPSHOT_EXPIRES <= _t.monotonic(),
          "C5 invalidate가 만료를 현재시각 이하로(다음 refresh 재조회 유도)")

    # 빈 스냅샷 = fail-closed(콜드 기본). 127.0.0.1도 차단.
    _set_allowed_hosts_for_test([])
    try:
        guard_url("http://127.0.0.1:8000/x")
        check(False, "C6 빈 스냅샷에서 127.0.0.1 — 통과해버림(fail-open!)")
    except SsrfBlocked:
        check(True, "C6 빈 스냅샷=fail-closed(127.0.0.1 차단)")


asyncio.run(_cache_checks())

# 정리: 스냅샷 비움(다른 테스트 누수 방지).
_set_allowed_hosts_for_test([])

print()
if _fails:
    print(f"❌ FAIL — {len(_fails)}건:")
    for f in _fails:
        print(f"   - {f}")
    sys.exit(1)
print("ALL PASS — VERIFY064_UNIT_OK")
