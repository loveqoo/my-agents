"""verify_110 — 엔드투엔드 오케스트레이션 시연(스펙 110, 106 잔여).

UI 저장 경로와 동일한 config(impl=orchestrate, capabilities=[rag:<collection>])로 조율형 에이전트를
만들고, **채팅 엔드포인트로 실제 1턴**을 돌려 브로커가 정말 위임하는지 trace의 `broker_invoke:*`
노드로 확인한다. 위임(delegate 노드)은 LLM과 독립이라 mock-llm으로 결정적으로 돈다.

체인 전 구간 관통: UI config(impl+capabilities) → build_broker(chat.py) → orchestrate delegate →
broker.invoke → trace `broker_invoke:rag:<col>`. verify_102는 그래프 레벨만 봤고, 이 테스트가
**채팅 엔드포인트 관통**(진짜 "한 화면에서 잇는")을 실측한다.

실행: cd packages/api && uv run python ../../tests/verify_110_e2e_orchestrate.py
"""

import asyncio
import uuid

import httpx

from api.auth import _token, current_principal
from api.main import app

# 위임(rag)은 **유저 세션 RBAC**를 통과해야 한다(머신 토큰=string principal은 deny-by-default —
# "능력 오케스트레이션 비대상", broker.py rbac_allows). 채팅 엔드포인트의 principal만 슈퍼유저로
# 오버라이드해 실제 유저 세션 경로를 재현한다(다른 엔드포인트는 Bearer 유지). is_superuser 우회로
# capability:rag가 허용된다. Session.user_id는 String(FK 아님)이라 스텁 UUID로 무해.
class _SuperPrincipal:
    id = uuid.UUID("000000aa-0000-0000-0000-0000000000aa")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-110-super@local"


app.dependency_overrides[current_principal] = lambda: _SuperPrincipal()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


async def _chat_text(c: httpx.AsyncClient, agent_id: str, text: str) -> str:
    """채팅 1턴(SSE) 전체 본문을 문자열로. trace 이벤트(broker_invoke 노드 포함)가 여기 담긴다."""
    r = await c.post(
        f"/agents/{agent_id}/chat",
        json={"messages": [{"role": "user", "content": text}]},
    )
    return r.text


async def run() -> bool:
    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=90) as c:
        # 관측 가능한 cap: 존재하는 RAG 컬렉션 하나(청크 유무 무관 — invoke 자체가 broker_invoke 노드를 남김).
        cols = (await c.get("/collections")).json()
        if not cols:
            print("SKIP: RAG 컬렉션이 없습니다(시드 필요) — 시연 대상 cap 없음.")
            return False
        col = cols[0]["name"]
        cap = f"rag:{col}"
        query = col  # discover는 lexical 부분일치 — cap id의 부분문자열(컬렉션명)로 확정 발견.
        print(f"[setup] 조율형 위임 대상 cap = {cap}, 발견 질의 = {query!r}")

        base = {"model": "mock-llm", "prompt": "", "historyDepth": 6, "impl": "orchestrate"}
        made: list[str] = []
        try:
            # (1) 위임: 능력 1개 조율형 → 채팅 1턴 → broker_invoke 노드 존재.
            a = (await c.post("/agents", json={
                "name": f"orch-e2e-{uuid.uuid4().hex[:6]}",
                "config": {**base, "capabilities": [cap]},
            })).json()
            made.append(a["id"])
            ck(a.get("impl") == "orchestrate", "H0 조율형으로 저장(impl=orchestrate)")
            ck(a.get("capabilities") == [cap], f"H0 능력 저장({cap})")

            txt = await _chat_text(c, a["id"], query)
            ck("broker_invoke" in txt, "H1 채팅 1턴 → trace에 broker_invoke 노드(브로커가 실제 위임)")
            ck(f"broker_invoke:rag" in txt, f"H2 위임 대상 kind=rag ({cap})")

            # (2) 무위임 대조: 능력 0개 조율형 → broker_invoke 없음(deny-by-default, 위양성 배제).
            a0 = (await c.post("/agents", json={
                "name": f"orch-none-{uuid.uuid4().hex[:6]}",
                "config": {**base, "capabilities": []},
            })).json()
            made.append(a0["id"])
            txt0 = await _chat_text(c, a0["id"], query)
            ck("broker_invoke" not in txt0, "H3 무위임 대조 — 능력 0개면 broker_invoke 없음")
        finally:
            for aid in made:
                await c.delete(f"/agents/{aid}")

    ok = all(c for c, _ in checks)
    print("VERIFY110_OK" if ok else f"VERIFY110_FAIL({sum(1 for c, _ in checks if not c)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
