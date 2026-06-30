"""스펙 071 단위(시맨틱) — 카드 prefix-상대 endpoint 구제 + probe 404/410 정직화 (DB·네트워크 불요).

비겹침 사다리의 단위 rung(메모리 verification-ladder): 순수 로직만 떼어 본다.
프록시 path-prefix 배포의 카드가 루트상대 `/a2a`를 발행하면 `urljoin(candidate,"/a2a")`가 RFC상
prefix를 버리고 origin루트로 가 채팅 때 404가 났다. 071은 카드가 마운트된 prefix 하위로 resolve한다.

  R1  루트상대 `/a2a` + well-known(agent.json) candidate → prefix 보존
  R2  well-known 변형(agent-card.json)도 동일 prefix 추출
  R3  base-직접 candidate(well-known 접미 없음)도 prefix 보존
  R4  bare 상대 `a2a` → prefix 디렉터리 기준
  R5  절대 url passthrough(prefix 무관, host 유지)
  R6  origin루트 카드(prefix 없음) → 회귀 없음(origin루트 유지)
  R7  스킴상대 `//host` passthrough(http 전치)
  R8  깊은 루트상대 `/api/v1/a2a` → prefix 하위 전체 보존
  R9  보안 불변: 결과가 normalize_http_url 통과 — userinfo(@) 보유 절대 url은 거부(스펙 063 P1)
  R10 host 혼동 차단: bare `evil.com/a2a`가 타host로 안 가고 candidate host 하위 path로 묶임
  P1  probe 404 → dead(경로 부재 = 잘못된 endpoint)
  P2  probe 410 → dead(Gone)
  P3  probe 405/200/302/401 → live(도달, 라우트 존재)

실행: uv run --project packages/api python tests/verify_071_card_endpoint.py  (or: .venv/bin/python)
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import agent_card  # noqa: E402
from api import net_guard  # noqa: E402
from api.agent_card import _resolve_card_endpoint  # noqa: E402

_fails: list[str] = []


def ck(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ---------------- R: resolution 매트릭스 ----------------
WK = "https://h.test/ai-core/ccab-weekly-report/.well-known/agent.json"
WK_CARD = "https://h.test/ai-core/ccab-weekly-report/.well-known/agent-card.json"
BASE = "https://h.test/ai-core/ccab-weekly-report"
WANT = "https://h.test/ai-core/ccab-weekly-report/a2a"

ck(_resolve_card_endpoint("/a2a", WK) == WANT, f"R1 루트상대+well-known → prefix 보존 ({WANT})")
ck(_resolve_card_endpoint("/a2a", WK_CARD) == WANT, "R2 agent-card.json 변형도 동일 prefix")
ck(_resolve_card_endpoint("/a2a", BASE) == WANT, "R3 base-직접 candidate도 prefix 보존")
ck(_resolve_card_endpoint("a2a", WK) == WANT, "R4 bare 상대 → prefix 디렉터리 기준")
ck(
    _resolve_card_endpoint("https://other.test/a2a", WK) == "https://other.test/a2a",
    "R5 절대 url passthrough(host 유지·prefix 무관)",
)
ck(
    _resolve_card_endpoint("/a2a", "https://h.test/.well-known/agent.json") == "https://h.test/a2a",
    "R6 origin루트 카드(prefix 없음) → 회귀 없음",
)
ck(
    _resolve_card_endpoint("//other.test/a2a", WK) == "http://other.test/a2a",
    "R7 스킴상대 // passthrough(http 전치)",
)
ck(
    _resolve_card_endpoint("/api/v1/a2a", WK) == "https://h.test/ai-core/ccab-weekly-report/api/v1/a2a",
    "R8 깊은 루트상대 → prefix 하위 전체 보존",
)

# R9 — 보안 불변: 결과는 normalize_http_url을 통과하므로 userinfo(@) 절대 url은 거부(스펙 063 P1).
try:
    _resolve_card_endpoint("https://user@evil.test/a2a", WK)
    ck(False, "R9 userinfo(@) 절대 url 거부 기대했으나 통과")
except ValueError:
    ck(True, "R9 userinfo(@) 보유 url → ValueError(normalize 통과 검증 유지)")

# R10 — host 혼동 차단: bare는 타host로 안 간다(candidate host 하위 path로 묶임).
r10 = _resolve_card_endpoint("evil.test/a2a", WK)
ck(
    r10 == "https://h.test/ai-core/ccab-weekly-report/evil.test/a2a",
    f"R10 bare host 혼동 차단(candidate host 하위로 묶임, 실제={r10})",
)

# R11 — dot-segment canonical화·origin clamp(적대 리뷰 071 F4): literal `..`가 stored endpoint에
# 안 남고, origin 위로는 못 올라간다(urljoin clamp). host는 candidate host 유지.
r11 = _resolve_card_endpoint("/../../admin", WK)
ck(
    r11 == "https://h.test/admin",
    f"R11 dot-segment clamp(origin 위 불가·literal .. 제거, 실제={r11})",
)
ck(".." not in _resolve_card_endpoint("/x/../../y", WK), "R11 literal '..' 미잔존")


# ---------------- P: probe 404/410 정직화 ----------------
class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    def __init__(self, *, resp=None):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return self._resp


def _patch(status: int):
    orig = agent_card.httpx.AsyncClient
    agent_card.httpx.AsyncClient = lambda *a, **k: _FakeClient(resp=_FakeResp(status))
    return lambda: setattr(agent_card.httpx, "AsyncClient", orig)


async def _probe(status: int) -> bool:
    net_guard._set_allowed_hosts_for_test(["agent.internal.test"])
    restore = _patch(status)
    try:
        return await agent_card.probe_endpoint("http://agent.internal.test/a2a")
    finally:
        restore()
        net_guard._set_allowed_hosts_for_test([])


async def main() -> None:
    ck(await _probe(404) is False, "P1 probe 404 → dead(경로 부재=잘못된 endpoint)")
    ck(await _probe(410) is False, "P2 probe 410 → dead(Gone)")
    for s in (405, 200, 302, 401, 403):
        ck(await _probe(s) is True, f"P3 probe {s} → live(도달·라우트 존재)")

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (resolution 10 + probe 7)")


if __name__ == "__main__":
    asyncio.run(main())
