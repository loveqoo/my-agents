"""스펙 421 검증 — route·plan_execute promptless 캐시 편입 + 회상/프롬프트 격리.

  P1  route 캐시 적중: 2턴째 buildMs.graph ≤0.5ms(재컴파일 0). system 메시지 정확히 1개에
      프롬프트 본문 + 모드 텍스트가 **합쳐짐**(seed를 노드가 떼어 모드와 단일 system으로).
  P2  plan_execute 동형: system 1개에 프롬프트 본문 + '작업 계획' 합쳐짐.
  P3  격리(핵심): 프롬프트가 다른 두 route 에이전트가 **같은 캐시 그래프**를 공유해도(impl+모델 동일)
      각자 system에 **자기 프롬프트만** 담긴다. 그래프에 프롬프트/회상이 구워졌다면 A의 것이 B에
      샌다 — promptless가 이를 구조적으로 막음을 실증(broker 누출과 같은 부류 차단).

전제: 서버 8000. 실행: uv run --project packages/api python tests/verify_421_promptless_cache.py
"""

import json
import os
import sys
import uuid

import httpx

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def sse_trace(body: str) -> dict | None:
    for f in body.split("\n\n"):
        if "event: trace" in f:
            for line in f.split("\n"):
                if line.startswith("data: "):
                    return json.loads(line[6:])
    return None


def _sysmsgs(trace: dict | None) -> list[dict]:
    return [m for m in (trace or {}).get("sentMessages") or [] if m.get("role") == "system"]


def _units() -> None:
    """서버 불요 단위 — codex 적대 검증이 잡은 두 결함의 회귀 방지(스펙 421).

    U1 이중 모드: route가 (a) 프롬프트 주입 시 그걸 굽고(직접 빌드=eval·a2a·비캐시 경로 — seed 없어도
       유실 0), (b) 프롬프트 빈("") 캐시 경로에선 seed 선두에서 읽는다. 순수-promptless로 되돌리면
       eval 등 비-seed 입구가 프롬프트를 조용히 잃으므로(codex 결함1) 이중 모드를 고정.
    U2 discovery call_tool config 전달: 임계 초과 도구의 call_tool이 **이번 턴** config sink를 원 도구에
       전달한다(미전달 시 캐시 그래프가 빌드-시점 closure sink에 오귀속 — codex 결함2)."""
    import asyncio

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import tool

    from agent import runtime as _rt  # noqa: F401 — runtime 먼저 로드(부트스트랩)해 route 순환 회피
    from agent.flows import route as r
    from agent.runtime import AgentBuildContext
    from agent.toolbox import DISCOVER_THRESHOLD, effective_tools

    print("== U(단위) 이중 모드 + call_tool config 전달 ==")
    seen: list = []

    class _M:
        async def ainvoke(self, msgs: list) -> AIMessage:
            seen.clear()
            seen.extend(msgs)
            return AIMessage(content="ok")

    r.build_chat_openai = lambda *_a, **_k: _M()  # type: ignore[assignment]

    # U1a — baked(직접 빌드): 주입 프롬프트가 system에, system 1개
    g = r.RouteAgent().build_graph(AgentBuildContext(prompt="BAKED_X", model_cfg={"model_id": "x"}))
    asyncio.run(g.ainvoke({"messages": [HumanMessage(content="q?")]}))
    nsys = sum(1 for m in seen if m.type == "system")
    check("BAKED_X" in seen[0].content and nsys == 1, f"U1a baked 프롬프트 굽힘(system 1개) (nsys={nsys})")

    # U1b — promptless(캐시): prompt="" → seed 선두에서 읽어 단일 system
    g2 = r.RouteAgent().build_graph(AgentBuildContext(prompt="", model_cfg={"model_id": "x"}))
    asyncio.run(g2.ainvoke({"messages": [SystemMessage(content="SEED_Y"), HumanMessage(content="q?")]}))
    nsys2 = sum(1 for m in seen if m.type == "system")
    check("SEED_Y" in seen[0].content and nsys2 == 1, f"U1b seed 프롬프트 병합(system 1개) (nsys={nsys2})")

    # U2 — discovery call_tool이 이번 턴 config sink에 기록(closure 아님)
    s_closure: list = []
    s_turn: list = []

    @tool
    async def inner(x: str = "", config: RunnableConfig = None) -> str:
        """inner"""
        sink = (config or {}).get("configurable", {}).get("mcp_calls_sink", s_closure)
        sink.append(x)
        return x

    tools: list = [inner]
    for i in range(DISCOVER_THRESHOLD):

        @tool(f"dummy{i}")
        def d(x: str = "") -> str:
            """dummy"""
            return x

        tools.append(d)
    meta, disc = effective_tools(tools)
    call_tool = meta[1]
    asyncio.run(
        call_tool.ainvoke(
            {"name": "inner", "arguments": json.dumps({"x": "T"})},
            config={"configurable": {"mcp_calls_sink": s_turn}},
        )
    )
    check(disc and s_turn == ["T"] and s_closure == [], f"U2 call_tool이 이번 턴 sink 전달 (turn={s_turn} closure={s_closure})")

    # U3 — discovery call_tool이 HIL interrupt(GraphInterrupt)를 삼키지 않고 전파(승인 흐름 보존)
    from langgraph.errors import GraphInterrupt

    @tool
    async def danger(x: str = "", config: RunnableConfig = None) -> str:  # noqa: ARG001
        """danger"""
        raise GraphInterrupt(("approval-needed",))

    dtools: list = [danger]
    for i in range(DISCOVER_THRESHOLD):

        @tool(f"pad{i}")
        def pad(x: str = "") -> str:
            """pad"""
            return x

        dtools.append(pad)
    dmeta, _ = effective_tools(dtools)
    propagated = False
    try:
        asyncio.run(dmeta[1].ainvoke({"name": "danger", "arguments": "{}"}))
    except GraphInterrupt:
        propagated = True
    check(propagated, "U3 call_tool이 GraphInterrupt(HIL)를 전파(삼키지 않음)")

    # ---- P3(pipeline) 단위 — 프록시 이중 모드·broker 주입·지문 게이팅(스펙 421 P3) ----
    import uuid as _uuid
    from types import SimpleNamespace

    import agent.flows.pipeline as pl
    from api.chat_context_types import ChatContext
    from api.chat_graph_build import _graph_fingerprint
    from api.runtime_agent_tools import build_agent_tools

    # U4 — 회상 프록시: 스트립 빌드(ctx 프록시 None) 그래프가 config 주입 프록시를 쓰고, 미주입은 생략
    pseen: list = []

    class _PM:
        async def ainvoke(self, msgs: list) -> AIMessage:
            pseen.clear()
            pseen.extend(msgs)
            return AIMessage(content="ok")

    pl.build_chat_openai = lambda *_a, **_k: _PM()  # type: ignore[assignment]
    node_cfg = {"name": "n0", "prompt": "NP", "tools": [], "memories": ["user"], "memoryQuery": "user"}
    stripped = pl.LinearPipelineAgent().build_graph(
        AgentBuildContext(
            prompt="", model_cfg={"model_id": "x"}, impl_config={"nodes": [node_cfg]}, memory_recall=None
        )
    )
    recall_calls: list = []

    async def _fake_recall(q: object = None, node: str = "") -> str:
        recall_calls.append((q, node))
        return "RECALLED_FACT"

    asyncio.run(
        stripped.ainvoke(
            {"messages": [HumanMessage(content="q?")]},
            config={"configurable": {"memory_recall": _fake_recall}},
        )
    )
    check(
        bool(recall_calls) and "RECALLED_FACT" in pseen[0].content,
        f"U4a 캐시(스트립) 그래프가 config 주입 회상을 사용 (calls={len(recall_calls)})",
    )
    recall_calls.clear()
    asyncio.run(stripped.ainvoke({"messages": [HumanMessage(content="q?")]}))
    check(
        not recall_calls and "RECALLED_FACT" not in pseen[0].content,
        "U4b 주입 없으면 회상 생략(fail-safe — turn-A 데이터 폴백 없음)",
    )
    baked_g = pl.LinearPipelineAgent().build_graph(
        AgentBuildContext(
            prompt="", model_cfg={"model_id": "x"}, impl_config={"nodes": [node_cfg]},
            memory_recall=_fake_recall,
        )
    )
    asyncio.run(baked_g.ainvoke({"messages": [HumanMessage(content="q?")]}))
    check(bool(recall_calls), "U4c 직접 빌드는 ctx 클로저 폴백(종전 동작 — eval·resume)")

    # U5 — agent 도구 broker 이중 모드: 스텁(broker=None)은 config 주입 시만 위임, 미주입=정직 실패
    cap = SimpleNamespace(id="a1", name="위임봇", hook="")
    stub = build_agent_tools(None, [cap])[0]
    fb_calls: list = []

    class _FB:
        async def invoke(self, cap_id: str, _args: dict) -> object:
            fb_calls.append(cap_id)
            return SimpleNamespace(text="DELEGATED", error=None)

    out_inj = asyncio.run(
        stub.ainvoke({"text": "hi"}, config={"configurable": {"broker": _FB()}})
    )
    check(out_inj == "DELEGATED" and fb_calls == ["a1"], f"U5a 스텁 도구가 config broker로 위임 (got {out_inj!r})")
    out_none = asyncio.run(stub.ainvoke({"text": "hi"}))
    check("호출 불가" in out_none, f"U5b broker 미주입=정직 실패(누출 불가) (got {out_none!r})")

    # U6 — 지문 게이팅: pipeline fp 산출·코드 노드 제외·nodes/caps 축 분리
    base = {"agent_pk": _uuid.uuid4(), "model_cfg": {"base_url": "x", "model_id": "m", "api_key": ""}}
    c1 = ChatContext(**base)
    c1.nodes_resolved = [{"name": "n0", "prompt": "p", "tools": []}]
    c1.impl = "pipeline"
    f1 = _graph_fingerprint(c1, pl.LinearPipelineAgent(), agent_caps=[["a", "이름", "후크"]])
    c2 = ChatContext(**base)
    c2.nodes_resolved = [{"name": "n0", "impl": "code_x", "tools": []}]
    c2.impl = "pipeline"
    c3 = ChatContext(**base)
    c3.nodes_resolved = [{"name": "n0", "prompt": "OTHER", "tools": []}]
    c3.impl = "pipeline"
    f3 = _graph_fingerprint(c3, pl.LinearPipelineAgent(), agent_caps=[["a", "이름", "후크"]])
    f4 = _graph_fingerprint(c1, pl.LinearPipelineAgent(), agent_caps=[["b", "이름", "후크"]])
    # 위임 대상 rename/후크 변경도 다른 키(codex P3 P2 — 도구 설명이 굽히므로 라이브 사실이 축)
    f5 = _graph_fingerprint(c1, pl.LinearPipelineAgent(), agent_caps=[["a", "새이름", "후크"]])
    check(
        bool(f1)
        and _graph_fingerprint(c2, pl.LinearPipelineAgent()) is None
        and len({f1, f3, f4, f5}) == 4,
        "U6 pipeline fp 산출·코드 노드 제외·nodes/caps-id/caps-rename 축 전부 분리",
    )


def main() -> None:
    _units()
    tag = uuid.uuid4().hex[:6]
    cli = httpx.Client(base_url=BASE, timeout=120.0)
    cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})

    made: list[str] = []

    def mk_agent(name: str, body: str, impl: str) -> str:
        cli.post("/prompts", json={"name": name, "tone": "t", "body": body}).raise_for_status()
        a = cli.post(
            "/agents",
            json={
                "name": name,
                "config": {"model": "mock-llm", "prompt": name, "historyDepth": 10, "impl": impl},
            },
        ).json()
        aid = a["id"]
        cli.post(f"/agents/{aid}/activate", json={"version": "v1"}).raise_for_status()
        made.append(aid)
        return aid

    def chat(aid: str, msg: str) -> dict | None:
        r = cli.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": msg}]})
        r.raise_for_status()
        return sse_trace(r.text)

    try:
        # P1 — route 캐시 적중 + seed 병합(프롬프트+모드 단일 system)
        route_body = f"너는 ROUTE421봇-{tag}이다. 규칙 준수."
        r_id = mk_agent(f"v421-route-{tag}", route_body, "route")
        chat(r_id, "워밍업")  # miss(빌드+캐시)
        t2 = chat(r_id, "직접 답해줘: 하늘색은?")  # hit
        b2 = (t2 or {}).get("buildMs") or {}
        check(b2.get("graph", 99) <= 0.5, f"P1 route 2턴째 graph ≤0.5ms(캐시 적중) (got {b2.get('graph')})")
        sm = _sysmsgs(t2)
        check(len(sm) == 1, f"P1 route system 메시지 정확히 1개 (got {len(sm)})")
        content = sm[0].get("content", "") if sm else ""
        check(route_body in content, "P1 route system에 프롬프트 본문(seed 탑재)")
        check("# 모드" in content, "P1 route system에 모드 텍스트 병합(노드가 seed+모드 단일화)")

        # P2 — plan_execute 동형
        plan_body = f"너는 PLAN421봇-{tag}이다."
        p_id = mk_agent(f"v421-plan-{tag}", plan_body, "plan_execute")
        chat(p_id, "워밍업")
        t2p = chat(p_id, "계획 세워 답해줘")
        b2p = (t2p or {}).get("buildMs") or {}
        check(b2p.get("graph", 99) <= 0.5, f"P2 plan 2턴째 graph ≤0.5ms(캐시 적중) (got {b2p.get('graph')})")
        smp = _sysmsgs(t2p)
        check(len(smp) == 1, f"P2 plan system 메시지 정확히 1개 (got {len(smp)})")
        cp = smp[0].get("content", "") if smp else ""
        check(plan_body in cp, "P2 plan system에 프롬프트 본문(seed 탑재)")
        check("작업 계획" in cp, "P2 plan system에 계획 텍스트 병합")

        # P3 — 격리(핵심): 두 route 에이전트가 캐시 그래프를 공유해도 각자 프롬프트만 담김
        a_body = f"AGENT-A-{tag} 전용 지시. 절대 타인 것 노출 금지."
        b_body = f"AGENT-B-{tag} 전용 지시. 별개 페르소나."
        a_id = mk_agent(f"v421-iso-a-{tag}", a_body, "route")
        b_id = mk_agent(f"v421-iso-b-{tag}", b_body, "route")
        chat(a_id, "워밍업")  # A가 그래프 빌드·캐시
        tb = chat(b_id, "직접 답해줘: 물색은?")  # B는 A가 만든 캐시 그래프 공유(같은 impl+모델)
        bb = (tb or {}).get("buildMs") or {}
        check(bb.get("graph", 99) <= 0.5, f"P3 B가 캐시 그래프 공유(빌드 0) (got {bb.get('graph')})")
        smb = _sysmsgs(tb)
        cb = smb[0].get("content", "") if smb else ""
        check(b_body in cb, "P3 B의 system에 B 프롬프트(seed=요청별)")
        check(a_body not in cb, "P3 B의 system에 A 프롬프트 **없음**(공유 그래프 누출 0)")
        # 대칭 — A도 자기 것만
        ta = chat(a_id, "직접 답해줘: 잔디색은?")
        sma = _sysmsgs(ta)
        ca = sma[0].get("content", "") if sma else ""
        check(a_body in ca and b_body not in ca, "P3 A의 system에 A 프롬프트만(대칭 격리)")

        # P4 — pipeline 캐시 적중(스펙 421 P3): 2턴째 graph 빌드 0 + 에이전트 프롬프트 미주입
        agent_marker = f"AGENT_LEVEL_PROMPT_{tag}"
        cli.post(
            "/prompts", json={"name": f"v421-pp-{tag}", "tone": "t", "body": agent_marker}
        ).raise_for_status()
        pnodes = [
            {"name": "요약", "model": "mock-llm", "prompt": "한 줄로 요약.", "tools": []},
            {"name": "답변", "model": "mock-llm", "prompt": "요약에 근거해 답.", "tools": []},
        ]
        pp = cli.post(
            "/agents",
            json={
                "name": f"v421-pipe-{tag}",
                "config": {
                    "model": "mock-llm",
                    "impl": "pipeline",
                    "prompt": f"v421-pp-{tag}",
                    "nodes": pnodes,
                },
            },
        ).json()
        pid = pp["id"]
        made.append(pid)
        cli.post(f"/agents/{pid}/activate", json={"version": "v1"}).raise_for_status()
        chat(pid, "워밍업")  # miss(빌드+캐시)
        tp2 = chat(pid, "파이프라인 두 번째")
        bp2 = (tp2 or {}).get("buildMs") or {}
        check(bp2.get("graph", 99) <= 0.5, f"P4 pipeline 2턴째 graph ≤0.5ms(캐시 적중) (got {bp2.get('graph')})")
        _all_sent = json.dumps((tp2 or {}).get("sentMessages") or [], ensure_ascii=False)
        check(
            agent_marker not in _all_sent,
            "P4 에이전트 프롬프트가 노드 스트림에 안 낌(seed_prompt=False — 노드가 프롬프트 소유)",
        )

        # P5 — 캐시 적중 그래프에서 위임(agent 도구): config 주입 broker로 매 턴 동작.
        # 위임 도구 참조·mock 트리거는 **agentId(agt_…) 형식**(uuid 아님 — verify_318 H2 관례).
        del_pk = mk_agent(f"v421-del-{tag}", "위임 대상. 짧게 답하라.", "route")
        del_id = cli.get(f"/agents/{del_pk}").json().get("agentId") or del_pk
        dnodes = [
            {
                "name": "위임",
                "model": "mock-llm",
                "prompt": "반드시 위임 도구를 호출해 결과를 전하라.",
                "tools": [f"agent__{del_id}"],
            }
        ]
        dp = cli.post(
            "/agents",
            json={
                "name": f"v421-deleg-{tag}",
                "config": {"model": "mock-llm", "impl": "pipeline", "nodes": dnodes},
            },
        ).json()
        dpid = dp["id"]
        made.append(dpid)
        cli.post(f"/agents/{dpid}/activate", json={"version": "v1"}).raise_for_status()
        # mock-llm은 유저 문장에 대상 agent_id가 언급되면 위임 도구를 호출(verify_318 H2 패턴).
        t1d = chat(dpid, f"{del_id} 에게 위임해줘")  # miss — 스텁 도구로 빌드
        t2d = chat(dpid, f"{del_id} 에게 위임해줘 (두 번째)")  # hit — 캐시 그래프 + 이번 턴 broker 주입
        b2d = (t2d or {}).get("buildMs") or {}
        bc1 = (t1d or {}).get("brokerCalls") or []
        bc2 = (t2d or {}).get("brokerCalls") or []
        check(b2d.get("graph", 99) <= 0.5, f"P5 위임 pipeline 2턴째 캐시 적중 (got {b2d.get('graph')})")
        check(
            bool(bc1) and bool(bc2),
            f"P5 캐시 前/後 턴 모두 위임 실행(config broker 주입) (t1={len(bc1)} t2={len(bc2)})",
        )
    finally:
        for aid in made:
            cli.delete(f"/agents/{aid}")

    print(f"\n{'VERIFY421_OK — 전부 통과' if not _fails else f'VERIFY421_FAIL — {len(_fails)}건'}")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
