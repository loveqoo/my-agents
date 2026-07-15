"""verify_119 — 에이전트 평가 하네스(스펙 119, 방향 3).

하네스가 **결정적 수치**를 내고 **판별한다**(통과/실패가 점수를 움직임)를 실측. 단위(score 산술·판별력)
+ 관통(실 채팅 mock-llm: 능력 있는 조율형은 위임 trace, 없는 건 무위임).

실행: cd packages/api && uv run python ../../tests/verify_119_eval_harness.py
"""
import asyncio
import json
import os
import sys
import uuid

# eval_harness는 스펙 137에서 packages/api/src/api/로 승격(제품 코어 단일 출처) — 경로 갱신.

import httpx  # noqa: E402

from api.eval_harness import (  # noqa: E402
    EvalCase,
    no_error,
    output_nonempty,
    run_eval,
    trace_has,
    trace_lacks,
)

from api.auth import _token, current_principal  # noqa: E402
from api.main import app  # noqa: E402


class _SuperPrincipal:
    id = uuid.UUID("000000cc-0000-0000-0000-0000000000cc")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-119-super@local"


app.dependency_overrides[current_principal] = lambda: _SuperPrincipal()

_fails = []
def check(c, m):
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


async def unit():
    # 고정 관측 run_fn(결정적) — case.meta["obs"]를 그대로 돌려줌.
    async def fake_run(case):
        return case.meta["obs"]

    good = {"output": "답", "trace_nodes": ["analyze", "broker_invoke:rag:x"], "error": False}
    bad = {"output": "", "trace_nodes": [], "error": True}

    cases = [
        EvalCase("c1", "x", [trace_has("broker_invoke:"), no_error(), output_nonempty()], {"obs": good}),
        EvalCase("c2", "x", [no_error(), output_nonempty()], {"obs": bad}),  # 실패 예정(error·empty)
    ]
    rep = await run_eval(cases, fake_run)
    check(rep.total == 2, "U1 total=2")
    check(rep.passed == 1, f"U1 passed=1(c1 통과·c2 실패) (got {rep.passed})")
    check(abs(rep.score - 0.5) < 1e-9, f"U1 score=0.5 산술 (got {rep.score})")

    # 판별력: 같은 관측이라도 assertion을 틀리게 걸면 점수가 내려가야(항상-통과 아님).
    wrong = [EvalCase("w", "x", [trace_lacks("broker_invoke:")], {"obs": good})]  # good엔 broker_invoke 있음→실패
    repw = await run_eval(wrong, fake_run)
    check(repw.score == 0.0, f"U2 틀린 assertion→score 0(판별력) (got {repw.score})")
    right = [EvalCase("r", "x", [trace_has("broker_invoke:")], {"obs": good})]
    check((await run_eval(right, fake_run)).score == 1.0, "U2 맞는 assertion→score 1")

    # run_fn 예외도 error 관측으로 접고 **뒤 case를 계속** 평가(codex 119 P2 — 2 case로 continue 증명).
    async def flaky(case):
        if case.name == "boom":
            raise RuntimeError("run fail")
        return good
    repb = await run_eval(
        [EvalCase("boom", "x", [no_error()], {}), EvalCase("ok", "x", [no_error()], {})], flaky
    )
    check(repb.total == 2 and repb.passed == 1,
          f"U3 예외 case 뒤에도 계속 평가(total 2·passed 1) (got {repb.total}/{repb.passed})")

    # 빈 asserts = 자동 통과 금지(codex 119 P1) — 명시 실패.
    repe = await run_eval([EvalCase("noassert", "x", [], {"obs": good})], fake_run)
    check(repe.score == 0.0, f"U5 빈 asserts case → 실패(조용한 초록 금지) (got {repe.score})")

    # scorer 예외 = 그 assert 실패, 전체 평가는 계속(codex 119 P2).
    def _boom_scorer():
        return ("boom_scorer", lambda o: 1 / 0)  # ZeroDivisionError
    reps = await run_eval([EvalCase("s", "x", [_boom_scorer(), no_error()], {"obs": good})], fake_run)
    check(reps.total == 1 and reps.passed == 0,
          "U5 scorer 예외 → 해당 assert 실패(전체 중단 아님)")

    # 빈 데이터셋 경계.
    check((await run_eval([], fake_run)).score == 0.0, "U4 빈 데이터셋→score 0.0(신호 없음)")


async def passthrough():
    """실 채팅(mock-llm) run_fn으로 하네스가 실제 에이전트를 결정적으로 평가하는지 관통."""
    made = []

    async def chat_run_fn(case):
        aid = case.meta["agent_id"]
        acc, trace, event = [], None, None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                     headers={"Authorization": f"Bearer {_token()}"}, timeout=120) as c:
            async with c.stream("POST", f"/agents/{aid}/chat",
                                json={"messages": [{"role": "user", "content": case.input}]}) as resp:
                # HTTP/비-SSE 실패를 error=False로 숨기면 negative case가 거짓 통과(codex 119 P1). 상태 확인.
                if resp.status_code != 200:
                    return {"output": "", "trace_nodes": [], "error": True, "http_status": resp.status_code}
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
        return {"output": "".join(acc), "trace_nodes": nodes, "error": False}

    try:
        auth = {"Authorization": f"Bearer {_token()}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                     headers=auth, timeout=120) as c:
            cols = (await c.get("/collections")).json()
            if not cols:
                print("SKIP passthrough: RAG 컬렉션 없음(시드 필요)")
                return
            cap = f"rag:{cols[0]['name']}"
            base = {"model": "mock-llm", "prompt": "", "historyDepth": 6, "impl": "orchestrate"}
            a_cap = (await c.post("/agents", json={"name": f"ev-cap-{uuid.uuid4().hex[:6]}",
                     "config": {**base, "capabilities": [cap]}})).json()
            a_none = (await c.post("/agents", json={"name": f"ev-none-{uuid.uuid4().hex[:6]}",
                      "config": {**base, "capabilities": []}})).json()
            made += [a_cap["id"], a_none["id"]]

        cases = [
            EvalCase("위임함", cols[0]["name"], [trace_has("broker_invoke:"), no_error(), output_nonempty()],
                     {"agent_id": a_cap["id"]}),
            EvalCase("무위임", cols[0]["name"], [trace_lacks("broker_invoke:"), no_error()],
                     {"agent_id": a_none["id"]}),
        ]
        rep = await run_eval(cases, chat_run_fn)
        print(f"  [passthrough] {rep.summary()}")
        check(rep.score == 1.0, f"P1 실 채팅 평가 통과율 1.0(능력 있=위임·없=무위임 결정적) (got {rep.summary()})")
        # 판별: 능력 없는 에이전트에 "위임했어야" assertion을 걸면 실패로 잡힘.
        mis = [EvalCase("오판", cols[0]["name"], [trace_has("broker_invoke:")], {"agent_id": a_none["id"]})]
        repm = await run_eval(mis, chat_run_fn)
        check(repm.score == 0.0, f"P2 무능력 에이전트에 위임-기대→score 0(판별) (got {repm.score})")
    finally:
        for aid in made:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                         headers={"Authorization": f"Bearer {_token()}"}) as c:
                await c.delete(f"/agents/{aid}")


async def run():
    await unit()
    await passthrough()
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        return False
    print("✅ ALL PASS (VERIFY119_OK)")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
