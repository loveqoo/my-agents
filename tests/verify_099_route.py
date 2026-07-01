"""스펙 099 검증 — agent-flow 스킬 산출물 `route`(분기 라우터) 인터페이스 적합·구조·통합.

**핵심 불변식**: 스킬이 저작한 flow가 *신규 런타임 없이* 기존 시임에 그대로 적합해야 한다 —
`CustomAgent` Protocol 적합(089 conforming), 조건분기 그래프가 mock ctx로 컴파일되고 노드열이
선언대로(085), 실행 시 **한 분기만** 실 노드 타임라인에 발화(과적합 없음). 등록은 신뢰 dict 조회만.

검증 사다리(비겹침):
  [U] 단위 — Protocol 적합·매니페스트 정직·노드 구조·분기 순수함수 결정성·conformance 분류·레지스트리 드리프트0.
  [H] 통합(in-process ASGI + 실 그래프) — ui+impl=route chat 스트림 → 토큰 + **실 노드 타임라인**;
      질문("?")→answer_a 분기만, 평서문→answer_b 분기만(조건분기 실증).

실행: uv run --project packages/api python tests/verify_099_route.py  (통합엔 API 서버 필요)
"""

import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from agent import runtime as agent_rt  # noqa: E402
from agent.runtime import (  # noqa: E402
    AgentBuildContext,
    AgentManifest,
    CustomAgent,
    classify_runtime,
    get_agent_impl,
    list_agent_impls,
)
from agent.flows.route import RouteAgent, classify_route  # noqa: E402

from api import chat as chat_mod  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 실 LLM 없이 그래프 구조만 검사할 수 있게 mock model_cfg 사용(085과 동일 규칙).
_MODEL_CFG = {
    "base_url": "http://127.0.0.1:8000/_remote/v1",
    "model_id": "mock-chat",
    "api_key": "sk-noauth",
    "params": {},
}


def _ctx(**kw) -> AgentBuildContext:
    base = dict(persona="당신은 테스트 라우터입니다.", model_cfg=_MODEL_CFG, tools=[])
    base.update(kw)
    return AgentBuildContext(**base)


# ================================================================ [U] 단위
def unit_checks() -> None:
    print("[U] 단위 — Protocol 적합·매니페스트 정직·노드 구조·분기 결정성·conformance·드리프트0")

    # U1 Protocol 적합 + 매니페스트 정직.
    ra = RouteAgent()
    check(isinstance(ra, CustomAgent), "U1 RouteAgent는 CustomAgent 적합(runtime_checkable)")
    m = ra.describe()
    check(isinstance(m, AgentManifest), "U1 describe()→AgentManifest")
    check(m.name == "route", f"U1 매니페스트 name='route' (got {m.name!r})")
    # 그래프에 interrupt 없음 → supports_hil은 정직하게 False여야 한다(과대선언 금지).
    check(m.supports_hil is False, "U1 supports_hil=False(인터럽트 없음 — 정직 표기)")

    # U2 구조 — mock ctx로 컴파일, 노드가 선언대로(조건분기 3노드). plan_execute와 구조 상이(누수 측정).
    g = ra.build_graph(_ctx())
    check(hasattr(g, "astream"), "U2 그래프가 astream 보유(호출 계약)")
    nodes = set(g.get_graph().nodes)
    check({"classify", "answer_a", "answer_b"} <= nodes,
          f"U2 조건분기 3노드(classify·answer_a·answer_b) (got {nodes})")
    check("plan" not in nodes, "U2 plan 노드 없음(plan_execute와 구조 상이 = 과적합 측정 토대)")

    # U3 conformance 분류 + 신뢰 로딩 — ui+impl=route → conforming, 인스턴스 적합.
    check(get_agent_impl("route") is not None, "U3 get_agent_impl('route') 적합 인스턴스 반환")
    check(classify_runtime("ui", "route") == "conforming",
          f"U3 classify_runtime(ui, route)=='conforming' (got {classify_runtime('ui', 'route')})")
    # 원격 소스는 여전히 non_conforming(무회귀), 미등록 키는 config_error(신뢰경계 유지).
    check(classify_runtime("code", "route") == "non_conforming",
          "U3 code 소스는 non_conforming(원격 fallback, route 무관)")
    check(classify_runtime("ui", "route_does_not_exist") == "config_error",
          "U3 미등록 키 → config_error(만회 없음)")

    # U4 분기 순수함수 결정성 — 질문("?")→"a", 평서문→"b". 모델 없이 검증(스킬 규약: 분기 로직 순수함수).
    check(classify_route("이건 무엇인가요?") == "a", "U4 '?' 포함 → 분기 'a'(직답)")
    check(classify_route("오늘 날씨가 좋다.") == "b", "U4 '?' 없음 → 분기 'b'(부연·정리)")
    check(classify_route("") == "b", "U4 빈 입력 → 분기 'b'(기본)")

    # U5 레지스트리 드리프트 0 — 'route' 등록됨, 문자열→import 경로 없음(신뢰경계 무회귀).
    check("route" in list_agent_impls(), "U5 route가 신뢰 레지스트리에 등록됨")
    check(get_agent_impl("os.system") is None, "U5 점경로 문자열 → None(import/eval 안 함)")
    check(list_agent_impls() == sorted(agent_rt._REGISTRY),
          "U5 list_agent_impls()=등록 키 집합(드리프트 0)")


# ================================================================ [H] 통합(in-process ASGI + 실 그래프)
async def http_checks() -> None:
    print("[H] 통합 — in-process ASGI: ui+impl=route 실 스트림 + 조건분기 실 노드 타임라인")
    import json

    import httpx
    from api.auth import _token
    from api.main import app

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    created_ids: list[str] = []

    async def _chat_trace(client, agent_db_id: str, text: str):
        acc, trace = [], None
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
        # H0 route 에이전트 생성(ui+impl=route). 자체 정리.
        r = await c.post("/agents", json={
            "name": f"v099-route-{uuid.uuid4().hex[:6]}",
            "config": {"model": "mock-llm", "persona": "", "historyDepth": 10, "impl": "route"},
        })
        check(r.status_code == 201, f"H0 route 에이전트 생성 201 (got {r.status_code})")
        out = r.json()
        rid = out["id"]
        created_ids.append(rid)
        check(out.get("impl") == "route", f"H1 AgentOut.impl 라운드트립='route' (got {out.get('impl')})")

        # H2 질문("?") → 토큰 + 타임라인이 [classify, answer_a], answer_b는 발화 안 함(조건분기 실증).
        t_a, tr_a = await _chat_trace(c, rid, "파이썬이 무엇인가요?")
        check(bool(t_a), "H2 질문 입력에 토큰 스트림")
        nodes_a = [n["node"] for n in (tr_a or {}).get("graph", [])]
        check("classify" in nodes_a and "answer_a" in nodes_a,
              f"H2 질문→실 노드 타임라인에 classify·answer_a (got {nodes_a})")
        check("answer_b" not in nodes_a, f"H2 질문→answer_b 분기 미발화(조건분기) (got {nodes_a})")
        check("call_model" not in nodes_a, "H2 실 노드열은 합성 call_model 안 씀")

        # H3 평서문(no "?") → 타임라인이 [classify, answer_b], answer_a는 발화 안 함.
        t_b, tr_b = await _chat_trace(c, rid, "파이썬은 프로그래밍 언어입니다.")
        check(bool(t_b), "H3 평서문 입력에 토큰 스트림")
        nodes_b = [n["node"] for n in (tr_b or {}).get("graph", [])]
        check("classify" in nodes_b and "answer_b" in nodes_b,
              f"H3 평서문→실 노드 타임라인에 classify·answer_b (got {nodes_b})")
        check("answer_a" not in nodes_b, f"H3 평서문→answer_a 분기 미발화(조건분기) (got {nodes_b})")

        # 정리.
        for aid in created_ids:
            await c.delete(f"/agents/{aid}")


async def main() -> None:
    unit_checks()
    await http_checks()
    print()
    if _fails:
        print(f"❌ 스펙 099 실패 {len(_fails)}건:")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 099 route 플로우 전부 통과 (단위 + 실 그래프 통합)")


asyncio.run(main())
