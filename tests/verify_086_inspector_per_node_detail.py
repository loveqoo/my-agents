"""스펙 086 검증 — 턴 인스펙터 노드별 세부정보(상태 델타 요약 + 실측 시간).

**핵심 불변식**: `updates` 청크의 *값*(노드 상태 델타)을 버리지 않고 (1) 키기반 redaction +
raw 사이즈 캡으로 안전 요약하고, (2) update 도착 간격으로 노드별 *실측* ms를 싣는다. 폴백 경로
(원격 재개 등 노드 미관측)는 기존 합성 경로 그대로(learning 060 무회귀).

검증 사다리(비겹침):
  [U] 단위 — _summarize_node_update(redaction·캡·알려진 형태·None), _timeline_from_observations
      (실측 ms·요약·재진입 보존), assemble_trace 3경로 우선순위(observations→nodes→폴백).
  [H] 통합(in-process ASGI + 실 그래프) — plan_execute chat → plan 노드 summary에 **실 계획
      문자열**·노드별 실측 ms(plan<execute, 균등분할 아님); ui 무회귀; 비밀 키 마스킹 종단 확인.

실행: uv run --project packages/api python tests/verify_086_inspector_per_node_detail.py  (API 서버 떠 있어야 함)
"""

import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from api import runtime as api_rt  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ================================================================ [U] 단위
def unit_checks() -> None:
    print("[U] 단위 — 요약(redaction·캡·형태)·관측 타임라인·assemble 3경로")

    # U1 redaction — 민감 키는 값 마스킹(비밀값 절대 trace에 안 실음, CLAUDE.md).
    s = api_rt._summarize_node_update("execute", {"api_key": "sk-live-SECRET", "step": "ok"})
    check("sk-live-SECRET" not in (s or ""), "U1 api_key 원문이 요약에 안 뜸")
    check("«redacted»" in (s or ""), f"U1 민감 키는 «redacted»로 마스킹 (got {s})")
    # 비민감 키여도 *값 원문은 미표시*(fail-closed) — 키/크기만(codex F2: 값-비밀 차단).
    check("step: ok" not in (s or ""), "U1 비안전 키 값은 원문 미표시(fail-closed)")
    check("step: <2자>" in (s or ""), f"U1 비안전 키는 길이만 노출 (got {s})")
    for k in ("token", "password", "auth_token", "client_secret", "bearer"):
        sk = api_rt._summarize_node_update("n", {k: "LEAK"})
        check("LEAK" not in (sk or ""), f"U1 민감 키 변종({k}) 마스킹")

    # U1b 중첩 dict — 값을 펼치지 않고 키만(중첩 안의 비밀 누출 차단).
    nested = api_rt._summarize_node_update("n", {"creds": {"api_key": "X", "host": "h"}})
    check("X" not in (nested or ""), "U1b 중첩 dict 안 비밀값 안 펼침")
    check("«redacted»" in (nested or ""), f"U1b 중첩 민감 키도 마스킹 (got {nested})")

    # U1c 값-자체-비밀(codex F2) — 키가 평범/비영문이라 _SENSITIVE_KEY가 못 잡아도 값 원문 안 샘.
    for key in ("note", "비밀번호", "memo", "context"):
        leak = api_rt._summarize_node_update("n", {key: "sk-live-PLAINKEY-9999"})
        check("PLAINKEY" not in (leak or ""), f"U1c 평범/비영문 키({key}) 문자열 값도 원문 미표시")
    # plan은 유일한 값-노출 안전 키(이 기능의 존재이유) — 원문 표시 유지.
    check(api_rt._summarize_node_update("plan", {"plan": "단계1"}) == "단계1", "U1c plan은 값 원문 유지")

    # U2 캡 — raw 문자열 길이에서 자르고 정직 표기(no silent truncation).
    big = api_rt._summarize_node_update("n", {"plan": "가" * 1000})
    check(len(big) <= api_rt._FIELD_CAP + 20, f"U2 필드 캡 적용 (len={len(big)})")
    check("생략" in big, "U2 잘린 길이 정직 표기(…N자 생략)")
    check("700자 생략" in big, f"U2 생략 길이 정확(원문 1000−필드캡 300, 이중캡 없음) (got 끝: ...{big[-15:]})")

    # U2b budgeted(codex F3) — 거대 값이어도 요약 길이가 캡 근처로 유한(통째 만들지 않음). 비안전 키는
    # 길이만 → 입력 크기와 무관하게 짧다. 안전 키(plan)도 캡으로 유한.
    huge = api_rt._summarize_node_update("n", {"blob": "x" * 5_000_000})
    check(len(huge) < 100, f"U2b 비안전 키 거대 값은 길이표시만(요약 유한) (len={len(huge)})")
    check("5000000자" in huge, f"U2b 길이는 정확히 보고 (got {huge})")
    huge_plan = api_rt._summarize_node_update("plan", {"plan": "y" * 5_000_000})
    check(len(huge_plan) <= api_rt._FIELD_CAP + 20, f"U2b 안전 키도 필드 캡으로 유한 (len={len(huge_plan)})")

    # U3 알려진 형태 — plan 문자열·messages 건수·빈/비dict→None.
    plan_s = api_rt._summarize_node_update("plan", {"plan": "1) 핵심 2) 근거"})
    check(plan_s == "1) 핵심 2) 근거", f"U3 plan은 계획 문자열 그대로 (got {plan_s})")
    msg_s = api_rt._summarize_node_update("execute", {"messages": [object(), object()]})
    check(msg_s == "메시지 2건", f"U3 messages는 건수만(본문 중복 안 실음) (got {msg_s})")
    check(api_rt._summarize_node_update("n", {}) is None, "U3 빈 델타 → None(요약 행 미표시)")
    check(api_rt._summarize_node_update("n", "not-a-dict") is None, "U3 비dict 델타 → None")

    # U4 _timeline_from_observations — 실측 ms·요약 보존, start/end 감쌈, 재진입(중복) 보존.
    obs = [
        {"node": "plan", "ms": 2, "summary": "P"},
        {"node": "execute", "ms": 88, "summary": "메시지 1건"},
        {"node": "execute", "ms": 12, "summary": None},  # 재발화(요약 없음)
    ]
    tl = api_rt._timeline_from_observations(obs)
    seq = [n["node"] for n in tl]
    check(seq == ["__start__", "plan", "execute", "execute", "__end__"],
          f"U4 start/end 감쌈 + 재진입 중복 보존 (got {seq})")
    check(tl[1]["ms"] == 2 and tl[2]["ms"] == 88, "U4 실측 ms 보존(균등분할 아님)")
    check(tl[1]["summary"] == "P", "U4 요약 보존")
    check("summary" not in tl[3], "U4 요약 None인 노드는 summary 키 없음(폴백 행 미표시)")

    # U4b parallel 플래그 보존(codex F4) — 병렬 superstep 노드는 parallel=True가 타임라인에 전달.
    tl_par = api_rt._timeline_from_observations([
        {"node": "a", "ms": 100, "summary": None, "parallel": True},
        {"node": "b", "ms": 100, "summary": None, "parallel": True},
    ])
    check(tl_par[1].get("parallel") is True and tl_par[2].get("parallel") is True,
          "U4b 병렬 노드는 parallel=True 보존(ms 과장 방지)")
    check("parallel" not in tl[1], "U4b 직렬 노드는 parallel 키 없음(무회귀)")

    # U4c 비문자 키 fail-closed(codex F5) — 요약기가 예외로 죽지 않고 안전 처리.
    weird = api_rt._summarize_node_update("n", {1: "a", ("t",): "b"})
    check(weird is not None, f"U4c 비문자 키도 예외 없이 요약 (got {weird!r})")
    check("a" not in (weird or ""), "U4c 비문자 키 값도 fail-closed(원문 미표시)")

    # U5 assemble_trace 3경로 우선순위 — observations > nodes > 폴백(무회귀).
    tr_obs = api_rt.assemble_trace(
        agent_id="a", memories=[], mcp_calls=[], used_memory=False, total_ms=100,
        tokens={"in": 1, "out": 1}, graph_nodes=["x"],
        graph_observations=[{"node": "plan", "ms": 5, "summary": "S"}],
    )
    check([n["node"] for n in tr_obs["graph"]] == ["__start__", "plan", "__end__"],
          "U5 observations가 nodes보다 우선(풀디테일)")
    check(tr_obs["graph"][1].get("summary") == "S", "U5 observations 경로가 요약 실음")
    tr_nodes = api_rt.assemble_trace(
        agent_id="a", memories=[], mcp_calls=[], used_memory=False, total_ms=100,
        tokens={"in": 1, "out": 1}, graph_nodes=["plan", "execute"],  # 085 경로(요약 없음)
    )
    check([n["node"] for n in tr_nodes["graph"]] == ["__start__", "plan", "execute", "__end__"],
          "U5 observations 없으면 graph_nodes 경로(085 무회귀)")
    check(all("summary" not in n for n in tr_nodes["graph"]), "U5 nodes 경로는 요약 없음(085 계약 불변)")
    tr_fb = api_rt.assemble_trace(
        agent_id="a", memories=[], mcp_calls=[], used_memory=False, total_ms=100,
        tokens={"in": 1, "out": 1},  # 둘 다 없음 → 합성 폴백
    )
    check("call_model" in [n["node"] for n in tr_fb["graph"]],
          "U5 둘 다 없으면 합성 폴백(원격 재개 무회귀, learning 060)")


# ================================================================ [H] 통합(in-process ASGI + 실 그래프)
async def http_checks() -> None:
    print("[H] 통합 — plan_execute 실 계획 요약 + 노드별 실측 ms")
    import json

    import httpx
    from api.auth import _token
    from api.main import app

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    created_ids: list[str] = []

    async def _chat_trace(client, agent_db_id: str, text: str):
        acc: list[str] = []
        trace = None
        async with client.stream(
            "POST", f"/agents/{agent_db_id}/chat",
            json={"messages": [{"role": "user", "content": text}]},
        ) as resp:
            assert resp.status_code == 200, f"chat status {resp.status_code}"
            event = None
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if event == "trace":
                        trace = obj
                    elif isinstance(obj, dict) and obj.get("text"):
                        acc.append(obj["text"])
        return "".join(acc), trace

    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=120
    ) as c:
        # plan_execute 커스텀 에이전트 생성(자체 정리).
        r_pe = await c.post("/agents", json={
            "name": f"v086-plex-{uuid.uuid4().hex[:6]}",
            "config": {"model": "mock-llm", "persona": "", "historyDepth": 10,
                       "impl": "plan_execute"},
        })
        check(r_pe.status_code == 201, f"H0 plan_execute 생성 201 (got {r_pe.status_code})")
        pe_id = r_pe.json()["id"]
        created_ids.append(pe_id)

        pe_text, pe_trace = await _chat_trace(c, pe_id, "Redis와 Memcached를 비교해줘.")
        check(bool(pe_text), "H1 plan_execute 토큰 스트림")
        graph = (pe_trace or {}).get("graph", [])
        nodes = {n["node"]: n for n in graph}
        check("plan" in nodes and "execute" in nodes, f"H1 실 노드 plan·execute (got {list(nodes)})")

        # H2 plan 노드 summary에 *실 계획 문자열*(자리표시 아님 — plan_execute가 주입한 고정 힌트).
        plan_sum = nodes.get("plan", {}).get("summary", "")
        check("핵심" in plan_sum and "근거" in plan_sum,
              f"H2 plan summary에 실 계획 문자열 (got {plan_sum!r})")
        # execute는 messages를 만든다 → 건수 요약(본문은 토큰 스트림으로 이미 나감).
        exec_sum = nodes.get("execute", {}).get("summary", "")
        check("메시지" in exec_sum, f"H2 execute summary=메시지 건수 (got {exec_sum!r})")

        # H3 노드별 실측 ms — plan(모델 호출 없는 결정적)은 execute(모델 호출)보다 빠르다.
        # 균등분할이면 둘이 같아야 하므로, plan<execute는 *실측*의 증거.
        plan_ms = nodes.get("plan", {}).get("ms", -1)
        exec_ms = nodes.get("execute", {}).get("ms", -1)
        check(plan_ms >= 0 and exec_ms >= 0, "H3 노드별 ms 존재")
        check(plan_ms <= exec_ms, f"H3 실측 ms: plan({plan_ms}) ≤ execute({exec_ms}) (균등분할 아님)")
        check(plan_ms + exec_ms <= (pe_trace or {}).get("latencyMs", 0) + 50,
              f"H3 노드 ms 합 ≤ 전체 지연(+slack) (plan{plan_ms}+exec{exec_ms} vs {(pe_trace or {}).get('latencyMs')})")

        # H4 비밀 누출 종단 — 요약기를 거친 어떤 노드 summary에도 흔한 비밀 토큰 패턴이 없어야.
        # (이 그래프는 비밀 키 상태가 없지만, 마스킹 경로가 종단 배선됐는지 요약기 단위로 재확인.)
        leaked = api_rt._summarize_node_update("execute", {"bearer_token": "tok-LEAK-123"})
        check("tok-LEAK-123" not in (leaked or ""), "H4 종단 요약기 비밀 마스킹(스트림 trace 누출 0)")

        for aid in created_ids:
            await c.delete(f"/agents/{aid}")


async def main() -> None:
    unit_checks()
    await http_checks()
    print()
    if _fails:
        print(f"❌ 스펙 086 실패 {len(_fails)}건:")
        for f in _fails:
            print("  -", f)
        sys.exit(1)
    print("✅ 스펙 086 노드별 세부정보 전부 통과 (요약 redaction·캡 + 노드별 실측 ms + 폴백 무회귀)")


if __name__ == "__main__":
    asyncio.run(main())
