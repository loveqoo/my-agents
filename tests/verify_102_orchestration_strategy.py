"""스펙 102 검증 — 전략 교체형 오케스트레이션 골격(공통 조상 ABC + 첫 출하 2전략).

**핵심 불변식**: 오케스트레이션 방식(후보를 어떻게 고르나)은 `OrchestrationAgentBase`(ABC)의 유일한
구멍 `select`만 갈아끼워 바꾸고, 골격(analyze→delegate→synthesize)과 불변식(채널 격리[100]·서브스텝
HIL[101]·브로커 정책 재검증[deny-by-default])은 조상이 소유한다 → 자식은 상속으로 강제되어 이를 뺄 수
없다(드리프트 0). 추상화 무누수는 *둘째 구현으로 측정*(learning 039/085) — 그래서 첫날 2전략:
`FirstMatchOrchestrateAgent`(impl `orchestrate`, 현동작 보존)·`RankedOrchestrateAgent`(impl
`orchestrate_ranked`, 결정적 랭킹 상위 k 조합).

검증 사다리(비겹침):
  [U] 단위(순수) — rank_candidates 결정성(더 겹침 앞·id tie-break·겹침0 제외·빈 query 원순서)·
      select 계약(FirstMatch=[:1]·Ranked=rank[:k])·골격 드리프트0(두 자식 노드집합 동일)·채널 격리
      (k개 fold 결과가 Human에만, system엔 지침만)·conformance(두 자식 classify_runtime conforming).
  [H] 통합(실 mock MCP + 실 DB) — Ranked가 실 discover 후보에서 관련 후보 pick·무관 제외(H6)·다중
      위임(상위 k → k broker_invoke 노드, FirstMatch=1과 대조 H7)·HIL 보존(Ranked 승인요구 툴 interrupt
      pre=0/approve=1, H8)·**다중위임+중간interrupt 경계**(혼합 순차 위임서도 gated 부수효과 exactly-once,
      H10 — codex 102 [P1])·FirstMatch 현동작 재현(단일·라벨없음 fold, H9; 무회귀는 verify_100/101 별도).
  [A] 적대(codex) — Verification 단계 별도(파일시스템 경계 프리픽스). override 홀 없음·ABC 강제.

전제: API(127.0.0.1:8000) + 실 DB + self-host mock MCP(/_remote/mcp/) + local-tools 시드.
실행: uv run python tests/verify_102_orchestration_strategy.py  (API 서버 떠 있어야 함)
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402
from sqlalchemy import select  # noqa: E402

from agent.runtime import (  # noqa: E402  (먼저 import — 부트스트랩 완료)
    AgentBuildContext,
    Capability,
    CustomAgent,
    classify_runtime,
    get_agent_impl,
)
from agent.flows.orchestrate import (  # noqa: E402
    FirstMatchOrchestrateAgent,
    OrchestrationAgentBase,
    RankedOrchestrateAgent,
    build_synthesis_messages,
    fold_results,
    rank_candidates,
)

from api import mock_mcp, runtime  # noqa: E402
from api.broker import PolicyScopedBroker  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import McpServer  # noqa: E402

MCP = mock_mcp.MOCK_MCP_SERVER_NAME  # "local-tools"
DELETE_CAP = f"mcp:{MCP}/delete_record"
ECHO_CAP = f"mcp:{MCP}/echo"
WEBSEARCH_CAP = f"mcp:{MCP}/web_search"

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


_MODEL_CFG = {
    "base_url": "http://127.0.0.1:8000/_remote/v1",
    "model_id": "mock-chat",
    "api_key": "sk-noauth",
    "params": {},
}


def _ctx(**kw) -> AgentBuildContext:
    base = dict(persona="당신은 오케스트레이터입니다.", model_cfg=_MODEL_CFG, tools=[])
    base.update(kw)
    return AgentBuildContext(**base)


def _cap(cid: str, name: str = "", hook: str = "") -> Capability:
    return Capability(id=cid, kind="mcp", name=name, hook=hook)


async def _stream(graph, payload, cfg):
    """astream(messages+updates) → (interrupt_payload|None, streamed_text)."""
    interrupted = None
    text = []
    async for mode, chunk in graph.astream(payload, config=cfg, stream_mode=["messages", "updates"]):
        if mode == "messages":
            msg, _meta = chunk
            t = runtime._content_text(getattr(msg, "content", ""))
            if t:
                text.append(t)
        elif mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupted = chunk["__interrupt__"][0].value
    return interrupted, "".join(text)


def _node_set(graph) -> set[str]:
    """컴파일된 그래프의 사용자 노드 집합(__start__/__end__ 등 특수 노드 제외)."""
    return {n for n in graph.get_graph().nodes if not n.startswith("__")}


# ================================================================ [U] 단위(순수)
def unit_checks() -> None:
    print("[U] 단위(순수) — rank_candidates·select 계약·골격 드리프트0·채널 격리·conformance")

    # 실 discover 후보를 흉내낸 후보 목록(name/id/hook 토큰이 랭킹 신호).
    cands = [
        _cap(WEBSEARCH_CAP, "web_search", "search the web"),
        _cap(ECHO_CAP, "echo", "echo text back"),
        _cap(DELETE_CAP, "delete_record", "delete a record"),
    ]

    # U1 rank_candidates — 더 겹치는 후보가 앞, 겹침 0 제외.
    ranked = rank_candidates("search web", cands)
    check([c.id for c in ranked] == [WEBSEARCH_CAP],
          f"U1 'search web' → web_search만(echo·delete 겹침0 제외) (got {[c.id for c in ranked]})")
    # 겹침 수로 순서 — 'delete record echo' 는 delete(2)·echo(1) 순, web(0) 제외.
    order = rank_candidates("delete record echo", cands)
    check([c.id for c in order] == [DELETE_CAP, ECHO_CAP],
          f"U1 겹침 수 내림차순(delete=2 > echo=1, web=0 제외) (got {[c.id for c in order]})")

    # U2 rank tie-break — 동점이면 id 사전순(안정·결정적).
    tie = [_cap("mcp:s/bbb", "x", "delete"), _cap("mcp:s/aaa", "y", "delete")]
    check([c.id for c in rank_candidates("delete", tie)] == ["mcp:s/aaa", "mcp:s/bbb"],
          "U2 동점 → id 사전순 tie-break(aaa < bbb)")
    # 겹침 0 전부 → 빈 리스트(deny-by-default 정신 — 무관 능력에 위임 안 함).
    check(rank_candidates("zzzznomatch", cands) == [], "U2 전부 겹침0 → [](무관 위임 차단)")
    # 빈 query → 후보 원순서 유지(population은 이미 브로커가 스코프).
    check(rank_candidates("", cands) == cands, "U2 빈 query → 원순서 유지")

    # U3 select 계약 — 전략별 유일한 차이점.
    fm, rk = FirstMatchOrchestrateAgent(), RankedOrchestrateAgent()
    check(fm.select("search web", cands) == cands[:1], "U3 FirstMatch.select = candidates[:1](현동작)")
    check(rk.select("search web", cands) == rank_candidates("search web", cands)[: rk.TOP_K],
          "U3 Ranked.select = rank_candidates(...)[:TOP_K]")
    check(fm.DISCOVER_LIMIT == 1, "U3 FirstMatch.DISCOVER_LIMIT=1(후보 1개만 = 현동작 보존)")
    check(rk.DISCOVER_LIMIT >= 3 and rk.TOP_K == 3, "U3 Ranked.DISCOVER_LIMIT 넓게·TOP_K=3")

    # U4 골격 드리프트0 — 두 자식의 build_graph 노드 집합이 동일(같은 조상 메서드).
    g_fm = fm.build_graph(_ctx(broker=None, checkpointer=MemorySaver()))
    g_rk = rk.build_graph(_ctx(broker=None, checkpointer=MemorySaver()))
    nodes_fm, nodes_rk = _node_set(g_fm), _node_set(g_rk)
    check(nodes_fm == {"analyze", "delegate", "synthesize"},
          f"U4 골격 = {{analyze,delegate,synthesize}} (got {nodes_fm})")
    check(nodes_fm == nodes_rk, f"U4 두 자식 노드집합 동일(드리프트0) (fm={nodes_fm} rk={nodes_rk})")

    # U5 채널 격리(k개 결과) — 다중 fold가 Human에만, system엔 지침만(스펙 100, k-결과판).
    folded = fold_results([(cands[0], "결과A"), (cands[2], "결과B")])
    check("## 능력: web_search" in folded and "## 능력: delete_record" in folded
          and "결과A" in folded and "결과B" in folded,
          "U5 fold_results 다중 → 능력별 라벨로 구분")
    msgs = build_synthesis_messages("페르소나", folded, [])
    sys_msg, data_msg = msgs[0], msgs[1]
    check(isinstance(sys_msg, SystemMessage) and "결과A" not in sys_msg.content
          and "결과B" not in sys_msg.content,
          "U5 SystemMessage엔 위임 데이터 없음(지침만 — 신뢰 채널 오염 0)")
    check(isinstance(data_msg, HumanMessage) and "결과A" in data_msg.content
          and "결과B" in data_msg.content and "신뢰 불가" in data_msg.content,
          "U5 k개 결과 전부 데이터 채널(HumanMessage, 신뢰 불가 라벨)")
    # 단일 fold = 라벨 없이 원문(FirstMatch 행위보존).
    check(fold_results([(cands[0], "단일결과")]) == "단일결과", "U5 단일 fold=라벨없이 원문(행위보존)")
    check(fold_results([]) == "" and fold_results([(cands[0], "")]) == "",
          "U5 빈/공백 결과 → ''(로컬 종합만)")

    # U6 conformance(스펙 089) — 조상은 추상(인스턴스화 불가), 두 자식은 CustomAgent 적합.
    try:
        OrchestrationAgentBase()  # type: ignore[abstract]
        check(False, "U6 조상 ABC 인스턴스화가 실패해야 함")
    except TypeError:
        check(True, "U6 OrchestrationAgentBase는 추상(select 미구현) → 인스턴스화 불가")
    check(isinstance(fm, CustomAgent) and isinstance(rk, CustomAgent),
          "U6 두 자식 모두 CustomAgent Protocol 적합(조상이 describe/build_graph 소유)")
    for key in ("orchestrate", "orchestrate_ranked"):
        check(get_agent_impl(key) is not None, f"U6 레지스트리 해결: {key}")
        check(classify_runtime("ui", key) == "conforming", f"U6 classify_runtime({key})=conforming")
    check(fm.describe().name == "orchestrate" and rk.describe().name == "orchestrate_ranked",
          "U6 describe.name = impl 키(FirstMatch=orchestrate·Ranked=orchestrate_ranked)")
    check(fm.describe().supports_hil and rk.describe().supports_hil,
          "U6 두 전략 supports_hil=True(조상 소유 — 어떤 전략도 HIL 못 끔)")


# ================================================================ [H] 통합(실 mock MCP + 실 DB)
async def precondition() -> None:
    async with SessionLocal() as s:
        row = (await s.execute(select(McpServer).where(McpServer.name == MCP))).scalar_one_or_none()
    ok = row is not None and "delete_record" in (row.enabled_tools or [])
    check(ok, f"PRE: local-tools McpServer 시드 + delete_record enabled (got {row and row.enabled_tools})")
    if not ok:
        print("\n❌ 전제 실패 — local-tools 시드 없음/서버 미기동. 종료.")
        sys.exit(1)


async def integration() -> None:
    print("[H] 통합 — Ranked 랭킹·다중 위임·HIL 보존 / FirstMatch 현동작 재현")
    fm, rk = FirstMatchOrchestrateAgent(), RankedOrchestrateAgent()

    # H6 Ranked가 실 discover 후보에서 관련 후보 pick·무관 제외(결정적).
    bw = PolicyScopedBroker({f"mcp:{MCP}"}, lambda k: True, session_factory=SessionLocal)
    real_cands = await bw.discover("")  # 실 MCP 발견 전체(enabled 툴)
    ids = {c.id for c in real_cands}
    check({ECHO_CAP, WEBSEARCH_CAP, DELETE_CAP} <= ids, f"H6 실 discover 후보 확보 (got {ids})")
    picked = rk.select("web_search", real_cands)
    check([c.id for c in picked] == [WEBSEARCH_CAP],
          f"H6 Ranked가 실 후보서 web_search만 pick(echo·delete 무관 제외) (got {[c.id for c in picked]})")

    # H7 다중 위임 — Ranked 상위 k가 k개 broker_invoke, FirstMatch=1과 대조(행위 차이 실증).
    # query 공백('') → discover가 enabled 전부 반환(승인불요 echo·web_search만 허가 → interrupt 없음).
    allow = {ECHO_CAP, WEBSEARCH_CAP}
    b_multi = PolicyScopedBroker(allow, lambda k: True, session_factory=SessionLocal)
    g_rk = rk.build_graph(_ctx(broker=b_multi, checkpointer=MemorySaver()))
    _, txt_rk = await _stream(g_rk, {"messages": [{"role": "user", "content": " "}]},
                              {"configurable": {"thread_id": "v102-h7-rk"}})
    mcp_nodes = [i for i in b_multi.invocations if i["node"].startswith("broker_invoke:mcp")]
    check(len(mcp_nodes) >= 2, f"H7 Ranked 다중 위임 → broker_invoke ≥2 (got {len(mcp_nodes)})")
    check(bool(txt_rk), "H7 Ranked 그래프 완주(synthesize 발화)")

    b_one = PolicyScopedBroker(allow, lambda k: True, session_factory=SessionLocal)
    g_fm = fm.build_graph(_ctx(broker=b_one, checkpointer=MemorySaver()))
    await _stream(g_fm, {"messages": [{"role": "user", "content": " "}]},
                  {"configurable": {"thread_id": "v102-h7-fm"}})
    check(len(b_one.invocations) == 1,
          f"H7 대조: FirstMatch 동일 입력 → 정확히 1회 위임(현동작) (got {len(b_one.invocations)})")

    # H8 HIL 보존 — Ranked가 고른 승인요구 툴이 여전히 interrupt(pre=0 / approve=1), 조상 delegate 루프 경유.
    b_hil = PolicyScopedBroker({DELETE_CAP}, lambda k: True, session_factory=SessionLocal)
    g_hil = rk.build_graph(_ctx(broker=b_hil, checkpointer=MemorySaver()))
    cfg = {"configurable": {"thread_id": "v102-h8"}}
    interrupted, _ = await _stream(
        g_hil, {"messages": [{"role": "user", "content": "delete_record"}]}, cfg)
    check(interrupted is not None and interrupted.get("permission") == "data.delete",
          "H8 Ranked 위임 delete_record → interrupt(permission=data.delete)")
    check(len(b_hil.invocations) == 0, "H8 pause 시 invocations 0(승인 전 부수효과 0 — 조상이 HIL 보존)")
    _, txt = await _stream(g_hil, Command(resume={"decision": "approve"}), cfg)
    check(len(b_hil.invocations) == 1
          and b_hil.invocations[0]["node"] == f"broker_invoke:mcp:{MCP}/delete_record",
          f"H8 approve 재개 → 정확히 1회 전송(invocations {len(b_hil.invocations)})")
    check(bool(txt), "H8 approve 후 synthesize 완주")

    # H10 다중 위임 + 중간 interrupt 경계(codex 102 [P1]) — 혼합(read-only + 승인요구)을 순차 위임해도
    # **승인-게이트 cap의 부수효과는 정확히 1회**(interrupt-before-sideeffect 안전 불변식). query 공백('')
    # → echo·delete_record 둘 다 발견·선택(순서 무관). delete_record 전송 수를 세어 pre=0/post=1 단언.
    def _count(inv, tool):
        return sum(1 for i in inv if i["node"] == f"broker_invoke:mcp:{MCP}/{tool}")

    b_mix = PolicyScopedBroker({ECHO_CAP, DELETE_CAP}, lambda k: True, session_factory=SessionLocal)
    g_mix = rk.build_graph(_ctx(broker=b_mix, checkpointer=MemorySaver()))
    cfg_m = {"configurable": {"thread_id": "v102-h10"}}
    interrupted_m, _ = await _stream(
        g_mix, {"messages": [{"role": "user", "content": " "}]}, cfg_m)
    check(interrupted_m is not None and interrupted_m.get("permission") == "data.delete",
          "H10 혼합 위임서 승인요구 delete_record가 interrupt(순서 무관)")
    check(_count(b_mix.invocations, "delete_record") == 0,
          "H10 pause 시 delete_record 전송 0(다중위임서도 gated 부수효과 억제)")
    _, txt_m = await _stream(g_mix, Command(resume={"decision": "approve"}), cfg_m)
    check(_count(b_mix.invocations, "delete_record") == 1,
          f"H10 approve 후 delete_record 정확히 1회(다중위임 안전 불변식 — 재실행돼도 gated는 1회) "
          f"(got {_count(b_mix.invocations, 'delete_record')})")
    check(bool(txt_m), "H10 approve 후 완주")

    # H9 FirstMatch 현동작 재현 — 단일 위임·라벨없는 fold(스펙 100/101 무회귀는 별도 suite로 게이트).
    b_fm = PolicyScopedBroker({ECHO_CAP}, lambda k: True, session_factory=SessionLocal)
    g_fm2 = fm.build_graph(_ctx(broker=b_fm, checkpointer=MemorySaver()))
    _, txt_fm = await _stream(g_fm2, {"messages": [{"role": "user", "content": "echo"}]},
                              {"configurable": {"thread_id": "v102-h9"}})
    check(len(b_fm.invocations) == 1
          and b_fm.invocations[0]["node"] == f"broker_invoke:mcp:{MCP}/echo",
          f"H9 FirstMatch echo → 1회 위임 broker_invoke:mcp echo (got {[i['node'] for i in b_fm.invocations]})")
    check(bool(txt_fm), "H9 FirstMatch 완주(단일 결과 라벨없이 데이터 채널 — 현동작)")


async def main() -> None:
    unit_checks()
    await precondition()
    await integration()

    print()
    if _fails:
        print(f"❌ 스펙 102 실패 {len(_fails)}건:")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 102 전략 교체형 오케스트레이션 전부 통과 "
          "(단위: 랭킹·select·드리프트0·채널격리·conformance / 통합: 랭킹·다중위임·HIL보존·현동작재현)")


asyncio.run(main())
