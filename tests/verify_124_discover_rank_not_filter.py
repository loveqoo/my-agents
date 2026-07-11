"""verify_124 — broker.discover 어휘 필터 → 랭킹 전환 (스펙 124, 조율형이 도구/문서/기억 못 쓰던 버그).

버그: discover가 `q in cap-text`(쿼리⊆능력)로 하드 필터해, 자연어 쿼리에선 허가된 능력이 전부 탈락
→ 조율형(broker.discover(query)로 위임 대상 탐색)이 아무 능력도 못 씀. 수정: 어휘 겹침을 하드 필터가
아니라 **랭킹**으로(0 겹침도 유지, limit까지 반환).

검증(실 broker + 실 DB local-tools MCP):
  - D1 실 자연어 쿼리에서도 허가 능력 반환(버그 재현 반전).
  - D2 랭킹: 쿼리 토큰과 겹치는 능력이 앞으로.
  - D3 빈 쿼리도 여전히 전체 반환(무회귀).
  - D4 RBAC 거부 kind는 여전히 안 뜸(게이트 무회귀 — 랭킹 전환이 게이트 우회 안 함).
  - D5 limit 경계 존중.

전제: DB 마이그레이션·seed(local-tools MCP) 적용. 실행: uv run python tests/verify_124_discover_rank_not_filter.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from api.broker import PolicyScopedBroker  # noqa: E402
from api.broker import BrokerContext, build_providers  # noqa: E402, F401  (스펙 294)

_fails: list[str] = []
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _broker(allowlist, rbac=lambda kind, name=None: True):
    return PolicyScopedBroker(allowlist=allowlist, rbac_allows=rbac, providers=build_providers(BrokerContext(user_id="u-verify124")))


async def main() -> None:
    NAT = "오늘 뭐 했지 기억나?"  # 자연어 — 능력 이름의 부분문자열이 아님(버그 재현 쿼리)

    # ── D1: 실 자연어 쿼리에서도 memory 능력 반환 ──
    caps = await _broker(["memory:user"]).discover(NAT, limit=10)
    check([c.id for c in caps] == ["memory:user"], f"D1 자연어 쿼리서 memory:user 반환(버그 반전, got {[c.id for c in caps]})")

    # ── D1b: mcp local-tools도 자연어 쿼리서 반환 ──
    mcaps = await _broker(["mcp:local-tools"]).discover(NAT, limit=10)
    ids = {c.id for c in mcaps}
    check(len(mcaps) >= 1 and any("local-tools" in i for i in ids),
          f"D1b 자연어 쿼리서 mcp local-tools 툴 반환(got {sorted(ids)})")

    # ── D2: 랭킹 — 'search web' 쿼리는 web_search를 앞으로 ──
    ranked = await _broker(["mcp:local-tools"]).discover("search the web please", limit=10)
    rids = [c.id for c in ranked]
    if rids:
        check(rids[0].endswith("/web_search"),
              f"D2 겹치는 능력(web_search)이 1순위(got {rids})")
    else:
        check(False, "D2 랭킹 후보 없음(예상 밖)")

    # ── D3: 빈 쿼리도 전체 반환(무회귀) ──
    empty = await _broker(["memory:user", "memwrite:user"]).discover("", limit=10)
    check({c.id for c in empty} == {"memory:user", "memwrite:user"},
          f"D3 빈 쿼리 전체 반환(got {sorted(c.id for c in empty)})")

    # ── D4: RBAC 거부 → 여전히 안 뜸(게이트 무회귀) ──
    denied = await _broker(["memory:user"], rbac=lambda kind, name=None: False).discover(NAT, limit=10)
    check(denied == [], f"D4 RBAC 전부 거부면 discover 공집합(게이트 우회 없음, got {[c.id for c in denied]})")

    # ── D4b: allowlist 비면 공집합(deny-by-default 무회귀) ──
    none_allowed = await _broker([]).discover(NAT, limit=10)
    check(none_allowed == [], "D4b allowlist 비면 공집합(deny-by-default)")

    # ── D5: limit 경계 ── (local-tools 3툴 → limit=2면 2개)
    limited = await _broker(["mcp:local-tools"]).discover(NAT, limit=2)
    check(len(limited) <= 2, f"D5 limit=2 존중(got {len(limited)})")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
