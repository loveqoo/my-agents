"""verify_117 — A2A 협업 실증 + 위임 승인 게이트(스펙 117, 방향 1).

verify_100 H4는 external 위임을 돌리나 원격이 에러(도달불가)라 **성공 협업**은 실증 못 한다. 이 테스트는
`a2a_client.a2a_stream`을 결정적 프레임을 내도록 패치해(네트워크 하위 경계는 042/060/063 검증분 재사용)
에이전트→에이전트 위임이 **실제 성공**(원격 답이 종합에 도달)함을 관통 실증하고, 옵트인 승인 게이트를
검증한다.

  Part A (HTTP E2E)  — 조율형이 등록 A2A 에이전트에 위임 → trace broker_invoke:agent + 원격에 질의 도달.
  Part B (단위)      — AgentProvider.approval_for opt-in: 플래그 없음→None(무회귀)·있음→payload·승인==전송.
  Part B (통합/그래프) — requires_approval 대상 위임 → 전송 이전 interrupt(a2a 호출 0)·approve 1회·reject 0회.

실행: cd packages/api && uv run python ../../tests/verify_117_a2a_collaboration_and_approval.py
"""

import asyncio
import json
import uuid

import httpx

from api.auth import _token, current_principal
from api.main import app
from api.broker import BrokerContext, build_providers  # noqa: E402, F401  (스펙 294)


# 위임은 유저 세션 RBAC 통과 필요(머신토큰 deny-by-default, learning 110). 채팅 EP principal만 슈퍼유저로.
class _SuperPrincipal:
    id = uuid.UUID("000000bb-0000-0000-0000-0000000000bb")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-117-super@local"


app.dependency_overrides[current_principal] = lambda: _SuperPrincipal()

_fails = []


def check(c, m):
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


# --- a2a_client.a2a_stream 패치(결정적 + 호출 기록) — broker가 `a2a_client.a2a_stream`으로 모듈 속성
#     참조하므로 모듈 속성 재할당이 곧 패치. 네트워크 없이 관통. ---
_a2a_calls = []


async def _fake_a2a_stream(endpoint, token, text, streaming=False, context_id=None):
    _a2a_calls.append({"endpoint": endpoint, "text": text})
    yield {"text": f"[원격답변] {text}"}


async def part_a_http_e2e():
    from api.db import SessionLocal
    from api.models import Agent
    from sqlalchemy import delete

    pfx = f"v117{uuid.uuid4().hex[:6]}"
    target_name = (
        f"{pfx}partner"  # 채팅 질의가 이 이름을 부분포함해야 lexical discover가 찾음(learning 110)
    )
    target_id = f"{pfx}-tgt"
    async with SessionLocal() as s:
        s.add(
            Agent(
                agent_id=target_id,
                name=target_name,
                source="external",
                endpoint="https://partner.example/a2a",
                config={"card": {"description": "협업 파트너 에이전트"}},
            )
        )
        await s.commit()

    made = []
    _a2a_calls.clear()
    try:
        auth = {"Authorization": f"Bearer {_token()}"}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t", headers=auth, timeout=120
        ) as c:
            r = await c.post(
                "/agents",
                json={
                    "name": f"{pfx}-orch",
                    "config": {
                        "model": "mock-llm",
                        "prompt": "",
                        "historyDepth": 10,
                        "impl": "orchestrate",
                        "capabilities": [target_id],
                    },
                },
            )
            check(r.status_code == 201, f"A0 조율형 생성 201 (got {r.status_code})")
            oid = r.json()["id"]
            made.append(oid)

            acc, trace, event = [], None, None
            async with c.stream(
                "POST",
                f"/agents/{oid}/chat",
                json={"messages": [{"role": "user", "content": target_name}]},
            ) as resp:
                check(resp.status_code == 200, f"A1 chat 200 (got {resp.status_code})")
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        p = line[5:].strip()
                        if p == "[DONE]":
                            continue
                        try:
                            obj = json.loads(p)
                        except Exception:
                            continue
                        if event == "trace":
                            trace = obj
                        elif isinstance(obj, dict) and obj.get("text"):
                            acc.append(obj["text"])
            nodes = [n["node"] for n in (trace or {}).get("graph", [])]
            check(
                any(n.startswith("broker_invoke:agent:") for n in nodes),
                f"A2 위임 대상 kind=agent (broker_invoke:agent 노드) (got {nodes})",
            )
            check(
                len(_a2a_calls) == 1,
                f"A3 원격 A2A 정확히 1회 호출(협업 성공) (got {len(_a2a_calls)})",
            )
            check(
                _a2a_calls and target_name in _a2a_calls[0]["text"],
                "A4 사용자 질의가 원격에 전달(이음매 관통)",
            )
            check(bool(acc), "A5 종합 발화(원격 답이 데이터 채널 거쳐 종합됨)")
    finally:
        for aid in made:
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://t",
                    headers={"Authorization": f"Bearer {_token()}"},
                ) as c:
                    await c.delete(f"/agents/{aid}")
            except Exception:
                pass
        async with SessionLocal() as s:
            await s.execute(delete(Agent).where(Agent.agent_id == target_id))
            await s.commit()


async def part_schema_roundtrip():
    """codex 117 [P1] 회귀가드 — requires_approval가 API create 라운드트립서 보존되나(seed 우회 금지,
    learning 101). AgentConfig 스키마에 필드 없으면 model_dump가 조용히 드롭 → 게이트 비활성."""
    from api.db import SessionLocal
    from api.models import Agent
    from sqlalchemy import delete, select

    pfx = f"v117rt{uuid.uuid4().hex[:6]}"
    made = None
    try:
        auth = {"Authorization": f"Bearer {_token()}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t", headers=auth, timeout=60
        ) as c:
            r = await c.post(
                "/agents",
                json={
                    "name": f"{pfx}-rt",
                    "config": {"model": "mock-llm", "prompt": "", "requires_approval": True},
                },
            )
            check(r.status_code == 201, f"B0 생성 201 (got {r.status_code})")
            made = r.json()["id"]
        # DB에 저장된 config가 플래그를 보존했나(write-schema 관통 증명).
        async with SessionLocal() as s:
            row = (await s.execute(select(Agent).where(Agent.id == uuid.UUID(made)))).scalar_one()
            check(
                (row.config or {}).get("requires_approval") is True,
                f"B0 requires_approval API 라운드트립 보존(스키마 필드) (got {(row.config or {}).get('requires_approval')})",
            )
    finally:
        if made:
            async with SessionLocal() as s:
                await s.execute(delete(Agent).where(Agent.id == uuid.UUID(made)))
                await s.commit()


def part_b_unit():
    from api.broker import AgentProvider, _a2a_text

    class _Row:
        def __init__(self, name, config):
            self.name = name
            self.config = config

    ap = AgentProvider(session_factory=None)
    off = _Row("파트너", {"card": {}})
    on = _Row("파트너", {"requires_approval": True})

    check(
        ap.approval_for(off, "x", {"text": "질의"}) is None,
        "B1 requires_approval 없음 → None(게이트 없음·무회귀)",
    )
    pay = ap.approval_for(on, "x", {"text": "민감질의"})
    check(
        isinstance(pay, dict) and pay.get("action") == "a2a.delegate",
        "B2 requires_approval True → 승인 payload(a2a.delegate)",
    )
    check(pay and "파트너" in pay.get("summary", ""), "B2 payload summary에 대상 이름")
    # 승인한 것 == 전송되는 것(approval_for·invoke 동일 _a2a_text)
    args = {"text": "정확히 이 텍스트"}
    check(pay2 := ap.approval_for(on, "x", args), "B3 payload 존재")
    check(
        pay2["args"]["text"] == _a2a_text(args),
        "B3 승인 노출 텍스트 == invoke 전송 텍스트(승인==전송)",
    )


async def part_b_integration():
    """requires_approval 대상 위임을 최소 그래프로 돌려 interrupt-before-sideeffect 실측."""
    from typing import TypedDict

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    from api.broker import PolicyScopedBroker
    from api.db import SessionLocal
    from api.models import Agent
    from sqlalchemy import delete

    pfx = f"v117g{uuid.uuid4().hex[:6]}"
    tid = f"{pfx}-gtgt"
    async with SessionLocal() as s:
        s.add(
            Agent(
                agent_id=tid,
                name=f"{pfx}gate",
                source="external",
                endpoint="https://gate.example/a2a",
                config={"requires_approval": True},
            )
        )  # opt-in 게이트
        await s.commit()

    try:
        broker = PolicyScopedBroker(
            {tid},
            lambda k, name=None: True,
            providers=build_providers(BrokerContext(session_factory=SessionLocal)),
        )

        class S(TypedDict):
            out: str

        async def node(state):
            r = await broker.invoke(tid, {"text": "게이트질의"})
            return {"out": r.text}

        g = StateGraph(S)
        g.add_node("n", node)
        g.add_edge(START, "n")
        g.add_edge("n", END)
        graph = g.compile(checkpointer=MemorySaver())

        # (1) interrupt 이전 — a2a 호출 0
        _a2a_calls.clear()
        cfg = {"configurable": {"thread_id": f"{pfx}-approve"}}
        interrupted = None
        async for mode, chunk in graph.astream({}, config=cfg, stream_mode=["updates"]):
            if isinstance(chunk, dict) and "__interrupt__" in chunk:
                interrupted = chunk["__interrupt__"][0].value
        check(
            interrupted and interrupted.get("action") == "a2a.delegate",
            "B4 전송 이전 interrupt(a2a.delegate 승인 대기)",
        )
        check(len(_a2a_calls) == 0, f"B4 pause 시점 a2a 전송 0 (got {len(_a2a_calls)})")

        # (2) approve → 정확히 1회 전송
        async for _ in graph.astream(
            Command(resume={"decision": "approve"}), config=cfg, stream_mode=["updates"]
        ):
            pass
        check(len(_a2a_calls) == 1, f"B5 approve 후 a2a 정확히 1회 전송 (got {len(_a2a_calls)})")

        # (3) reject → 전송 0(fail-closed)
        _a2a_calls.clear()
        cfg_r = {"configurable": {"thread_id": f"{pfx}-reject"}}
        async for mode, chunk in graph.astream({}, config=cfg_r, stream_mode=["updates"]):
            pass
        async for _ in graph.astream(
            Command(resume={"decision": "reject"}), config=cfg_r, stream_mode=["updates"]
        ):
            pass
        check(len(_a2a_calls) == 0, f"B6 reject 후 a2a 전송 0(fail-closed) (got {len(_a2a_calls)})")
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Agent).where(Agent.agent_id == tid))
            await s.commit()


async def run():
    import api.a2a_client as a2ac

    a2ac.a2a_stream = (
        _fake_a2a_stream  # 패치(모듈 속성 재할당 = broker의 a2a_client.a2a_stream도 이것)
    )

    await part_a_http_e2e()
    await part_schema_roundtrip()
    part_b_unit()
    await part_b_integration()
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        return False
    print("✅ ALL PASS (VERIFY117_OK)")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
