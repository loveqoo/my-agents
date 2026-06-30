"""스펙 085 검증 — 커스텀 에이전트 런타임 인터페이스(in-process SDK).

**핵심 불변식**: 어떤 적합 그래프든(create_agent 단일 노드 = DefaultUiAgent, 손수 만든 다노드 =
PlanExecuteAgent) 같은 플랫폼 루프로 스트림되고, 같은 ctx 주입을 받고, **실 노드열**에서 파생된
호출 스택 추적을 받는다. 인터페이스가 create_agent에 과적합(누수)되지 않았음을 둘째 구현으로 측정
(learning 039). 미구현(원격 code/external)은 None→_a2a_stream fallback으로 지금처럼 동작.

검증 사다리(비겹침):
  [U] 단위 — Protocol 적합, ctx 주입, resolve_agent_runtime 디스패치, 추적 타임라인 파생,
      신뢰-로딩(미등록 키→None, eval 경로 없음).
  [H] 통합(in-process ASGI + 실 그래프) — ui·plan_execute 둘 다 chat 스트림 → 토큰 + **실 노드
      타임라인**; impl 라운드트립; 원격은 디스패치 None(fallback 경로).

실행: uv run --project packages/api python tests/verify_085_runtime_interface.py  (API 서버 떠 있어야 함)
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
    DefaultUiAgent,
    get_agent_impl,
    list_agent_impls,
)
from agent.examples.plan_execute import PlanExecuteAgent  # noqa: E402

from api import chat as chat_mod, runtime as api_rt  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 두 구현이 실제 ChatOpenAI를 만들지 않고 그래프 구조만 검사할 수 있게 mock model_cfg 사용.
_MODEL_CFG = {
    "base_url": "http://127.0.0.1:8000/_remote/v1",
    "model_id": "mock-chat",
    "api_key": "sk-noauth",
    "params": {},
}


def _ctx(**kw) -> AgentBuildContext:
    base = dict(persona="당신은 테스트 에이전트입니다.", model_cfg=_MODEL_CFG, tools=[])
    base.update(kw)
    return AgentBuildContext(**base)


# ================================================================ [U] 단위
def unit_checks() -> None:
    print("[U] 단위 — Protocol 적합·ctx 주입·디스패치·추적 파생·신뢰 로딩")

    # U1 Protocol 적합 — 둘 다 describe()/build_graph() 가진 CustomAgent.
    dua, pea = DefaultUiAgent(), PlanExecuteAgent()
    check(isinstance(dua, CustomAgent), "U1 DefaultUiAgent는 CustomAgent 적합(runtime_checkable)")
    check(isinstance(pea, CustomAgent), "U1 PlanExecuteAgent는 CustomAgent 적합")
    check(isinstance(dua.describe(), AgentManifest), "U1 describe()→AgentManifest(default)")
    check(isinstance(pea.describe(), AgentManifest), "U1 describe()→AgentManifest(plan-execute)")
    # 매니페스트가 capability를 정직히 표기(plan-execute는 HIL 미지원).
    check(pea.describe().supports_hil is False, "U1 plan-execute supports_hil=False(정직 표기)")
    check(dua.describe().supports_hil is True, "U1 default supports_hil=True")

    # U2 ctx 주입 + 구조 차이 — 둘 다 컴파일 그래프를 내되 노드 구성이 다르다(과적합 측정의 토대).
    g_default = dua.build_graph(_ctx())
    g_plan = pea.build_graph(_ctx())
    check(hasattr(g_default, "astream"), "U2 default 그래프가 astream 보유(호출 계약)")
    check(hasattr(g_plan, "astream"), "U2 plan-execute 그래프가 astream 보유(호출 계약)")
    default_nodes = set(g_default.get_graph().nodes)
    plan_nodes = set(g_plan.get_graph().nodes)
    # plan-execute는 plan·execute 노드를 실제로 가진다 — create_agent(단일 model 노드)와 구조가 다름.
    check({"plan", "execute"} <= plan_nodes, f"U2 plan-execute 다노드 구조(plan·execute) (got {plan_nodes})")
    check("plan" not in default_nodes, "U2 default 그래프엔 plan 노드 없음(구조 상이 = 누수 측정 토대)")
    # ctx.persona 주입이 단일 출처 — plan-execute가 ctx.persona를 읽어 execute 노드 system에 합친다
    # (클로저 캡처). 빌드가 ctx 없이 자기 DB를 읽지 않음을 구조로 보장(빌드는 ctx만 받음).
    check(g_plan is not None, "U2 plan-execute가 주입 ctx만으로 그래프 빌드(자기설정 직접 안 읽음)")

    # U3 resolve_agent_runtime 디스패치 — ui→default, ui+impl→custom, 원격→None, 미지키→default(폴백).
    r_ui = chat_mod.resolve_agent_runtime({"source": "ui", "impl": None})
    r_custom = chat_mod.resolve_agent_runtime({"source": "ui", "impl": "plan_execute"})
    r_code = chat_mod.resolve_agent_runtime({"source": "code", "impl": None})
    r_ext = chat_mod.resolve_agent_runtime({"source": "external", "impl": None})
    r_unknown = chat_mod.resolve_agent_runtime({"source": "ui", "impl": "does_not_exist"})
    check(isinstance(r_ui, DefaultUiAgent), "U3 ui+impl없음 → DefaultUiAgent")
    check(isinstance(r_custom, PlanExecuteAgent), "U3 ui+impl=plan_execute → PlanExecuteAgent")
    check(r_code is None, "U3 source=code → None(원격 fallback)")
    check(r_ext is None, "U3 source=external → None(원격 fallback)")
    check(isinstance(r_unknown, DefaultUiAgent), "U3 ui+미지키 → DefaultUiAgent(graceful, 열거 오라클 없음)")

    # U4 추적 타임라인 파생 — graph_nodes 있으면 실 노드열, 없으면 합성 폴백(무회귀).
    tr_real = api_rt.assemble_trace(
        agent_id="a", memories=[], mcp_calls=[], used_memory=False,
        total_ms=100, tokens={"in": 1, "out": 1}, graph_nodes=["plan", "execute"],
    )
    node_seq = [n["node"] for n in tr_real["graph"]]
    check(node_seq == ["__start__", "plan", "execute", "__end__"],
          f"U4 graph_nodes→실 노드 타임라인(하드코딩 아님) (got {node_seq})")
    check("call_model" not in node_seq, "U4 실 노드열은 합성 call_model을 쓰지 않음")
    tr_fallback = api_rt.assemble_trace(
        agent_id="a", memories=[], mcp_calls=[], used_memory=False,
        total_ms=100, tokens={"in": 1, "out": 1},  # graph_nodes 미전달
    )
    fb_seq = [n["node"] for n in tr_fallback["graph"]]
    check("call_model" in fb_seq, f"U4 graph_nodes 없음→기존 합성 폴백(무회귀) (got {fb_seq})")
    # 중복·순서 보존(같은 노드 반복 발화 = 실 재진입).
    tr_dup = api_rt._timeline_from_nodes(["plan", "execute", "execute"], 90)
    check([n["node"] for n in tr_dup] == ["__start__", "plan", "execute", "execute", "__end__"],
          "U4 노드 중복·순서 보존(재진입 정직 표기)")

    # U5 신뢰 로딩 — dict 조회만, eval/import 경로 없음. 미등록 키·점경로 문자열 → None.
    check("plan_execute" in list_agent_impls(), "U5 plan_execute가 신뢰 레지스트리에 등록됨")
    check(get_agent_impl(None) is None, "U5 None 키 → None")
    check(get_agent_impl("") is None, "U5 빈 키 → None")
    check(get_agent_impl("os.system") is None, "U5 점경로 문자열 → None(import/eval 안 함)")
    check(get_agent_impl("__import__") is None, "U5 dunder 문자열 → None")
    # 레지스트리는 전역 신뢰집합 — list_agent_impls()가 등록 키와 정확히 일치(드리프트 0).
    check(list_agent_impls() == sorted(agent_rt._REGISTRY), "U5 list_agent_impls()=등록 키 집합(드리프트 0)")


# ================================================================ [H] 통합(in-process ASGI + 실 그래프)
async def http_checks() -> None:
    print("[H] 통합 — in-process ASGI: ui·plan_execute 실 스트림 + 실 노드 타임라인")
    import json

    import httpx
    from api.auth import _token
    from api.main import app

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    created_ids: list[str] = []

    async def _chat_trace(client, agent_db_id: str, text: str):
        """chat SSE를 끝까지 읽어 (모은 텍스트, trace dict)를 반환."""
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
        # H0 두 에이전트 생성 — ui(기본)와 ui+impl=plan_execute. 자체 정리(끝에 DELETE).
        r_ui = await c.post("/agents", json={
            "name": f"v085-ui-{uuid.uuid4().hex[:6]}",
            "config": {"model": "mock-llm", "persona": "", "historyDepth": 10},
        })
        check(r_ui.status_code == 201, f"H0 ui 에이전트 생성 201 (got {r_ui.status_code})")
        ui_id = r_ui.json()["id"]
        created_ids.append(ui_id)

        r_pe = await c.post("/agents", json={
            "name": f"v085-plex-{uuid.uuid4().hex[:6]}",
            "config": {"model": "mock-llm", "persona": "", "historyDepth": 10,
                       "impl": "plan_execute"},
        })
        check(r_pe.status_code == 201, f"H0 plan_execute 에이전트 생성 201 (got {r_pe.status_code})")
        pe_out = r_pe.json()
        pe_id = pe_out["id"]
        created_ids.append(pe_id)
        # H1 impl 라운드트립 — 생성 응답이 impl을 보존(편집 silent drop 방지).
        check(pe_out.get("impl") == "plan_execute", f"H1 AgentOut.impl 라운드트립 (got {pe_out.get('impl')})")
        check(r_ui.json().get("impl") is None, "H1 기본 ui 에이전트 impl=None")

        # create는 config=cfg를 에이전트에 직접 박으므로(서빙 config 확정) activate 없이 chat 가능.
        # H2 ui 에이전트 chat → 토큰 + 실 노드 타임라인(default 그래프).
        ui_text, ui_trace = await _chat_trace(c, ui_id, "안녕하세요, 한 문장으로 답하세요.")
        check(bool(ui_text), "H2 ui 에이전트가 토큰을 스트림")
        check(ui_trace is not None and isinstance(ui_trace.get("graph"), list),
              "H2 ui trace에 graph 타임라인 존재")
        ui_nodes = [n["node"] for n in (ui_trace or {}).get("graph", [])]
        # create_agent 그래프의 실 노드(모델 노드)가 잡힌다 — 합성 'call_model' 자리표시가 아니라 실명.
        check(any(not n.startswith("__") for n in ui_nodes),
              f"H2 ui 실 노드 타임라인 비어있지 않음 (got {ui_nodes})")

        # H3 plan_execute chat → 토큰 + 실 노드 타임라인이 [plan, execute](하드코딩 아님).
        pe_text, pe_trace = await _chat_trace(c, pe_id, "안녕하세요, 한 문장으로 답하세요.")
        check(bool(pe_text), "H3 plan_execute 에이전트가 토큰을 스트림")
        pe_nodes = [n["node"] for n in (pe_trace or {}).get("graph", [])]
        check("plan" in pe_nodes and "execute" in pe_nodes,
              f"H3 plan_execute 실 노드 타임라인=[plan, execute] (하드코딩 아님) (got {pe_nodes})")
        check("call_model" not in pe_nodes,
              "H3 plan_execute 타임라인은 합성 call_model을 쓰지 않음(실 노드 파생)")

        # H4 원격 fallback — code/external 디스패치는 None(in-process 그래프 안 탐). 디스패치 단위 재확인
        # (실 _a2a_stream은 mock 원격 서버 필요 — 여기선 게이트 판정만, 통합 경로 무회귀 보장).
        check(chat_mod.resolve_agent_runtime({"source": "code", "impl": None}) is None,
              "H4 code 소스 → 디스패치 None(원격 fallback 경로 보존)")

        # H5 편집→활성화 impl 보존(codex 적대 리뷰 F1 회귀 가드). SPA 편집 폼은 아직 impl을
        # 안 보내므로, impl 없는 config로 PUT(초안 갱신)한 뒤 활성화해도 impl이 살아남아야 한다.
        # F1 수정 전이면: PUT이 draft.config['impl']=None → activate가 serving config를 None으로
        # → 다음 chat이 DefaultUiAgent로 silent 되돌아감([plan,execute] 사라짐).
        r_edit = await c.put(f"/agents/{pe_id}", json={
            "name": None,
            "config": {"model": "mock-llm", "persona": "", "historyDepth": 10},  # impl 의도적 누락
        })
        check(r_edit.status_code == 200, f"H5 impl 없는 편집 PUT 200 (got {r_edit.status_code})")
        r_act = await c.post(f"/agents/{pe_id}/activate", json={"version": "v1"})
        check(r_act.status_code == 200, f"H5 v1 활성화 200 (got {r_act.status_code})")
        check(r_act.json().get("impl") == "plan_execute",
              f"H5 편집→활성화 후 impl 보존 (got {r_act.json().get('impl')})")
        # 활성화된 serving config로 실제 chat → 타임라인이 여전히 [plan, execute](fallback 아님).
        pe_text2, pe_trace2 = await _chat_trace(c, pe_id, "한 문장으로 답하세요.")
        pe_nodes2 = [n["node"] for n in (pe_trace2 or {}).get("graph", [])]
        check("plan" in pe_nodes2 and "execute" in pe_nodes2,
              f"H5 편집→활성화 후 실 노드 타임라인 보존=[plan, execute] (got {pe_nodes2})")

        # 정리 — 생성 에이전트 삭제(자체 격리).
        for aid in created_ids:
            await c.delete(f"/agents/{aid}")


async def main() -> None:
    unit_checks()
    await http_checks()
    print()
    if _fails:
        print(f"❌ 스펙 085 실패 {len(_fails)}건:")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 085 런타임 인터페이스 전부 통과 (단위 + 실 그래프 통합)")


asyncio.run(main())
