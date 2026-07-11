"""verify_130 — 조율형 RAG 검색의 인스펙터 표면화 백엔드 (스펙 130).

실 인프라(Obsidian 컬렉션, 로컬 임베더)로:
  V1 RagProvider invoke 성공 시 raw에 hits(건수)·topScore(최고 유사도) 구조화.
  V2 broker.invocations 엔트리에 hits/topScore 통과(+node/cap_id/ms 기존 유지).
  V3 본문·args 미포함(누출 0 — 087/092 계약 유지): 엔트리 키가 화이트리스트 안.
  V4 오류 경로: 미허가 cap invoke → error 표시(invocations에 error=True 또는 미기록 — 실제 거동 고정).
  V5 무위임: invocations 빈 브로커는 빈 리스트(트레이스 무회귀 전제).

전제: Obsidian 컬렉션 ready + 임베딩 모델 가용.
실행: uv run --project packages/api python tests/verify_130_broker_rag_visibility.py
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


async def main() -> None:
    b = PolicyScopedBroker(allowlist=["rag:Obsidian"], rbac_allows=lambda k, n=None: True, providers=build_providers(BrokerContext(user_id="v130")))

    res = await b.invoke("rag:Obsidian", {"text": "A/B 테스트에서 중요한 것은?"})
    raw = res.raw or {}
    check(res.error is None and raw.get("hits", 0) >= 1, f"V1a 성공 검색 raw.hits ≥ 1 (got {raw.get('hits')})")
    check(isinstance(raw.get("topScore"), float) and 0 < raw["topScore"] <= 1.0,
          f"V1b raw.topScore ∈ (0,1] (got {raw.get('topScore')})")

    check(len(b.invocations) == 1, f"V2a invocations 1건 (got {len(b.invocations)})")
    inv = b.invocations[0]
    check(inv.get("hits") == raw.get("hits") and inv.get("topScore") == raw.get("topScore"),
          f"V2b hits/topScore 통과 (got {inv})")
    check(inv.get("node", "").startswith("broker_invoke:rag:") and "ms" in inv and inv.get("cap_id") == "rag:Obsidian",
          "V2c 기존 필드(node/cap_id/ms) 유지")

    # 스펙 131: resultPreview(마스킹·캡된 결과 본문). 스펙 191: hitsDetail(히트별 카드)·minScore·query 추가.
    # 불변식은 "args 미포함 + 화이트리스트 밖 키 없음".
    allowed_keys = {"node", "cap_id", "ms", "hits", "topScore", "error", "resultPreview",
                    "hitsDetail", "minScore", "query"}
    check(set(inv.keys()) <= allowed_keys and "args" not in inv,
          f"V3 엔트리 키 화이트리스트(args 없음, 131 resultPreview·191 hitsDetail/minScore/query 허용) (got {set(inv.keys())})")
    # 스펙 191: hitsDetail은 의도된 구조(리스트) — 단, 각 히트의 본문 프리뷰는 캡+비밀 마스킹(누출 0).
    # 나머지 값은 여전히 스칼라(원문/args/거대데이터 없음). query는 마스킹된 검색어 문자열.
    for hd in inv.get("hitsDetail", []):
        check(set(hd.keys()) <= {"score", "filename", "collection", "textPreview"} and len(str(hd.get("textPreview", ""))) <= 241,
              f"V3b hitsDetail 항목=표시 필드만+프리뷰 캡 (got {set(hd.keys())})")
    check(all(not isinstance(v, (list, dict)) or k == "hitsDetail" for k, v in inv.items()),
          "V3c hitsDetail 외 값은 스칼라(컬렉션 본문류 리스트/딕트 없음)")

    denied = await b.invoke("rag:안보이는컬렉션", {"text": "x"})
    check(denied.error is not None, f"V4 미허가 cap → error (got {denied.error!r})")

    b2 = PolicyScopedBroker(allowlist=["rag:Obsidian"], rbac_allows=lambda k, n=None: True, providers=build_providers(BrokerContext(user_id="v130b")))
    check(b2.invocations == [], "V5 무위임 브로커 invocations 빈 리스트(트레이스 무회귀 전제)")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
