"""스펙 045 검증 — A2A liveness probe 시맨틱(#2) + 승인 status 필터 회귀.

probe_endpoint는 등록 시 endpoint 도달성을 판정해 status를 정직하게 정한다(무조건 online 제거).
보안 표면이므로(learning 028) 적대 입력에 예외 누출 없이 bool만 반환하는지, SSRF 가드가
loopback/사설을 dead로 떨구는지 결정적으로 검증한다. 네트워크 의존을 없애려 httpx는 목으로 주입.

검증:
  P1. probe_endpoint(None)·비http·빈문자 → False(크래시·예외 누출 없음).
  P2. loopback/사설(127.0.0.1) → False — SSRF 가드가 dead로 처리(예외 미누출).
  P3. allowlist 호스트 + httpx 응답(어떤 status) → True(도달=live).
  P4. allowlist 호스트 + httpx HTTPError(연결 실패) → False(미도달=dead).
  P5. list_approvals가 status 파라미터를 받는 시그니처(기본 None=전량, 회귀 가드).
  P6. AsyncClient가 follow_redirects=False로 생성 — 리다이렉트 SSRF 우회 차단(적대 리뷰).
  P7. httpx 외 예외(ValueError 등)도 흡수 → False(probe는 절대 raise 안 함).

실행: uv run python tests/verify_045_probe.py   (or: .venv/bin/python)
"""

import asyncio
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import agent_card  # noqa: E402
from api import approvals  # noqa: E402
from api import net_guard  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


_constructed_kwargs: list[dict] = []


class _FakeClient:
    """httpx.AsyncClient 대역 — get이 미리 정한 응답을 주거나 예외를 던진다.
    생성 kwargs를 기록해 follow_redirects 등 보안 옵션을 회귀 검증한다."""

    def __init__(self, *, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _patch_httpx(monkey):
    """agent_card.httpx.AsyncClient를 monkey(팩토리)로 교체하고 복원 함수를 반환."""
    orig = agent_card.httpx.AsyncClient
    agent_card.httpx.AsyncClient = monkey
    return lambda: setattr(agent_card.httpx, "AsyncClient", orig)


async def main() -> None:
    import httpx

    # P1 — 적대 입력
    for bad in (None, "", "not-a-url", "ftp://x", 123):
        r = await agent_card.probe_endpoint(bad)  # type: ignore[arg-type]
        check(r is False, f"P1 적대입력 {bad!r} → False")

    # P2 — loopback은 SSRF 가드가 dead로(예외 누출 없이 False)
    # 스펙 064: allowlist는 DB 스냅샷이 진실원 — DB 없는 테스트는 시seam으로 직접 고정(만료=inf → refresh no-op).
    net_guard._set_allowed_hosts_for_test([])
    r = await agent_card.probe_endpoint("http://127.0.0.1:9")
    check(r is False, "P2 loopback(127.0.0.1) → False (SSRF, 예외 미누출)")

    # P3 — allowlist 호스트 + 응답 도달 → True (httpx 목)
    net_guard._set_allowed_hosts_for_test(["agent.internal.test"])
    restore = _patch_httpx(lambda *a, **k: _FakeClient(resp=_FakeResp(405)))
    try:
        r = await agent_card.probe_endpoint("http://agent.internal.test/a2a")
        check(r is True, "P3 allowlist+응답(405도) → True (도달=live)")
    finally:
        restore()

    # P4 — allowlist 호스트 + 연결 실패 → False
    restore = _patch_httpx(lambda *a, **k: _FakeClient(exc=httpx.ConnectError("refused")))
    try:
        r = await agent_card.probe_endpoint("http://agent.internal.test/a2a")
        check(r is False, "P4 allowlist+ConnectError → False (미도달=dead)")
    finally:
        restore()

    # P6 — 클라이언트가 follow_redirects=False로 생성(리다이렉트 SSRF 우회 차단, 적대 리뷰 045).
    #   guard_url은 최초 URL만 검사하므로 추종하면 302→내부IP로 가드를 우회한다.
    _constructed_kwargs.clear()

    def _record(*a, **k):
        _constructed_kwargs.append(k)
        return _FakeClient(resp=_FakeResp(200))

    restore = _patch_httpx(_record)
    try:
        await agent_card.probe_endpoint("http://agent.internal.test/a2a")
        got = _constructed_kwargs[-1] if _constructed_kwargs else {}
        check(
            got.get("follow_redirects") is False,
            f"P6 AsyncClient(follow_redirects=False) — 리다이렉트 SSRF 차단 (실제={got.get('follow_redirects')!r})",
        )
    finally:
        restore()

    # P7 — httpx.HTTPError가 아닌 예외(ValueError 등)도 흡수해 False(probe는 절대 raise 안 함).
    restore = _patch_httpx(lambda *a, **k: _FakeClient(exc=ValueError("boom")))
    try:
        r = await agent_card.probe_endpoint("http://agent.internal.test/a2a")
        check(r is False, "P7 비-httpx 예외(ValueError)도 → False (등록 차단 방지, 예외 미누출)")
    finally:
        restore()
        net_guard._set_allowed_hosts_for_test([])

    # P5 — list_approvals 시그니처 회귀(status 기본 None=전량)
    sig = inspect.signature(approvals.list_approvals)
    p = sig.parameters.get("status")
    check(p is not None and p.default is None, "P5 list_approvals(status=None) 시그니처(전량 기본 보존)")

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (7 그룹)")


if __name__ == "__main__":
    asyncio.run(main())
