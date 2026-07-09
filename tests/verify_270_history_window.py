"""verify_270 (단위) — 노드별 단기 기억 창(HistoryWindowProxy) + 엔진 주입 (스펙 270).

  프록시: depth별 슬라이스=_window(전체, d)[:-1](현재 턴 분리)·캐시 공유·기본(None)=상속·0=빈대화·
     전체(음수/None default)·record=False면 기록 생략.
  엔진: carry 노드는 이전 대화 슬라이스가 [sys, 대화…, msgs] 순으로 주입·clean 노드는 대화 생략·
     노드가 자기 depth(미지정=None→상속)를 프록시에 전달·프록시 예외→대화 없이 노드 생존(graceful).

실행: uv run --project packages/api python tests/verify_270_history_window.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "agent", "src"))

import asyncio  # noqa: E402

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)


MODEL_CFG = {"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}}


async def main():
    from api.chat import _HistoryWindowProxy, _to_base_messages

    # 전체 대화 5개(마지막=현재 턴). _to_base_messages 왕복.
    conv_dicts = [
        {"role": "user", "content": "h1"}, {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "h2"}, {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "cur"},
    ]
    conv = _to_base_messages(conv_dicts)
    check([m.content for m in conv] == ["h1", "a1", "h2", "a2", "cur"], "_to_base_messages 왕복·순서")
    check(conv[-1].__class__.__name__ == "HumanMessage" and conv[1].__class__.__name__ == "AIMessage",
          "_to_base_messages role 매핑(user→Human·assistant→AI)")

    # ── 프록시 슬라이스: _window(전체, d)[:-1](현재 턴 분리) ──
    rec = []
    prox = _HistoryWindowProxy(conv, default_depth=2, records=rec)
    s_def = await prox(None, node="A")            # 기본 depth=2 → conv[-2:][:-1] = [a2]
    check([m.content for m in s_def] == ["a2"], f"기본(None)=상속 depth 2 → [a2] (got {[m.content for m in s_def]})")
    s4 = await prox(4, node="B")                  # conv[-4:][:-1] = [a1,h2,a2]
    check([m.content for m in s4] == ["a1", "h2", "a2"], f"depth 4 → [a1,h2,a2] (got {[m.content for m in s4]})")
    s0 = await prox(0, node="C")                  # conv[-1:][:-1] = []
    check(s0 == [], "depth 0 → 빈 대화(현재 턴만 시드됨)")
    s_all = await prox(-1, node="D")              # 음수=전체 → conv[:-1]
    check([m.content for m in s_all] == ["h1", "a1", "h2", "a2"], f"depth -1=전체 → 현재 제외 전부 (got {[m.content for m in s_all]})")
    check([r["depth"] for r in rec] == [2, 4, 0, -1] and [r["count"] for r in rec] == [1, 3, 0, 4],
          f"기록 (node,depth,count) (got {[(r['depth'], r['count']) for r in rec]})")
    check([r["node"] for r in rec] == ["A", "B", "C", "D"], "노드 귀속 기록")

    # 캐시 공유: 같은 depth 두 번 → 같은 리스트 객체(재계산 없음)
    a = await prox(4, node="E")
    b = await prox(4, node="F")
    check(a is b, "같은 depth=캐시 공유(동일 객체)")
    # record=False → 기록 생략(도구 루프 재진입)
    n_before = len(rec)
    await prox(4, node="G", record=False)
    check(len(rec) == n_before, "record=False → 기록 생략")

    # 빈 대화 방어
    prox_empty = _HistoryWindowProxy([], default_depth=20, records=[])
    check(await prox_empty(None, node="X") == [], "빈 대화 → 빈 슬라이스(무해)")

    # ── drop_last=False(재개 경로): DB 대화는 이전 대화만이라 마지막 안 버림(codex 270 High) ──
    prior_only = _to_base_messages([
        {"role": "user", "content": "p1"}, {"role": "assistant", "content": "p2"},
    ])
    prox_resume = _HistoryWindowProxy(prior_only, default_depth=20, records=[], drop_last=False)
    r_all = await prox_resume(None, node="R")
    check([m.content for m in r_all] == ["p1", "p2"], f"drop_last=False → 마지막(직전 assistant) 보존 (got {[m.content for m in r_all]})")
    r_1 = await prox_resume(1, node="R2")
    check([m.content for m in r_1] == ["p2"], f"drop_last=False depth1 → 마지막 1개(안 버림) (got {[m.content for m in r_1]})")

    # ── 엔진: 노드별 주입(carry=주입·clean=생략·자기 depth 전달·graceful) ──
    from agent.runtime import AgentBuildContext
    import agent.flows.pipeline as P
    from agent.flows.pipeline import LinearPipelineAgent

    seen = []  # (프롬프트 키, ainvoke에 넘어간 메시지 content 리스트)
    orig_model = P._model_from_node

    def fake_model(node, ctx):
        class _F:
            def bind_tools(self, tools):
                return self
            async def ainvoke(self, messages):
                seen.append((node["prompt"], [getattr(m, "content", "") for m in messages]))
                return AIMessage(content=f"OUT[{node['prompt']}]")
        return _F()

    P._model_from_node = fake_model
    try:
        hw_calls = []
        async def fake_window(depth=None, node="", record=True):
            hw_calls.append({"depth": depth, "node": node, "record": record})
            # depth를 마킹한 대화 슬라이스(엔진이 sys와 msgs 사이에 넣는지 확인용)
            return [HumanMessage(content=f"HIST(d={depth})")]

        nodes = [
            {"name": "n1", "prompt": "P1", "model_cfg": MODEL_CFG, "tools": [], "context": "carry", "historyDepth": 6},
            {"name": "n2", "prompt": "P2", "model_cfg": MODEL_CFG, "tools": [], "context": "carry"},  # depth 미지정→None(상속)
            {"name": "n3", "prompt": "P3", "model_cfg": MODEL_CFG, "tools": [], "context": "clean", "historyDepth": 40},
        ]
        ctx = AgentBuildContext(persona="", model_cfg=MODEL_CFG, tools=[],
                                impl_config={"nodes": nodes}, history_window=fake_window)
        await LinearPipelineAgent().build_graph(ctx).ainvoke({"messages": [HumanMessage(content="CUR")]})
        by_prompt = {k: v for k, v in seen}
        # n1(carry, depth6): sys, HIST(d=6), CUR 순 — 대화 슬라이스가 msgs 앞에 주입
        check(any("HIST(d=6)" in c for c in by_prompt["P1"]), f"엔진: carry n1에 depth6 슬라이스 주입 (got {by_prompt['P1']})")
        p1 = by_prompt["P1"]
        check(p1.index("HIST(d=6)") < p1.index("CUR"), "엔진: 슬라이스가 현재 입력(CUR) 앞에 온다")
        # n2(carry, 미지정): depth=None(상속) 전달
        check(any("HIST(d=None)" in c for c in by_prompt["P2"]), f"엔진: carry n2 미지정=None(상속) 전달 (got {by_prompt['P2']})")
        # n3(clean): 대화 슬라이스 없음(결정 가)
        check(not any(str(c).startswith("HIST") for c in by_prompt["P3"]), f"엔진: clean n3엔 대화 슬라이스 없음 (got {by_prompt['P3']})")
        # 프록시 호출: n1(6)·n2(None) 두 번, clean n3은 호출 안 함
        depths_called = [c["depth"] for c in hw_calls]
        check(depths_called == [6, None], f"엔진: carry 노드만 프록시 호출(clean 제외)·자기 depth 전달 (got {depths_called})")

        # graceful: 프록시 예외 → 대화 없이 노드 생존
        async def boom(depth=None, node="", record=True):
            raise RuntimeError("window down")
        ctx2 = AgentBuildContext(persona="", model_cfg=MODEL_CFG, tools=[],
                                 impl_config={"nodes": [nodes[0]]}, history_window=boom)
        out2 = await LinearPipelineAgent().build_graph(ctx2).ainvoke({"messages": [HumanMessage(content="X")]})
        check(len(out2["messages"]) == 2, "엔진: 프록시 예외에도 노드 생존(graceful)")

        # history_window=None(비노드형 시뮬레이션): 주입 없이 정상
        ctx3 = AgentBuildContext(persona="", model_cfg=MODEL_CFG, tools=[],
                                 impl_config={"nodes": [nodes[0]]}, history_window=None)
        seen.clear()
        await LinearPipelineAgent().build_graph(ctx3).ainvoke({"messages": [HumanMessage(content="Y")]})
        check(not any(str(c).startswith("HIST") for _, msgs in seen for c in msgs), "엔진: history_window=None이면 주입 없음(무회귀)")
    finally:
        P._model_from_node = orig_model

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
