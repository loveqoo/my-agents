"""verify_259 (단위) — 노드형 일렬 파이프라인 (스펙 259).

  U1 impl 등록: get_agent_impl("pipeline") 적합·list_agent_impls에 포함·classify_runtime conforming.
  U2 describe 정직: consumes에 nodes·supports_hil True.
  U3 normalize_nodes 순수: 프롬프트 없는/잡 노드 제외·순서 보존·tools 정규화.
  U4 그래프 구조: 3노드 config → 그래프 노드가 선언 노드 순서/개수와 일치(도구 노드 포함).
  U5 노드별 모델/도구: 각 노드가 자기 model_cfg로 모델 생성·도구는 ctx.tools에서 이름으로 필터
     (에이전트 밖 도구 이름은 무시 = 권한 상승 0).

실행: uv run --project packages/api python tests/verify_259_pipeline.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "agent", "src"))

from agent.runtime import (  # noqa: E402
    AgentBuildContext,
    classify_runtime,
    get_agent_impl,
    list_agent_impls,
)
from agent.flows.pipeline import LinearPipelineAgent, normalize_nodes  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)


from langchain_core.tools import StructuredTool  # noqa: E402


def _fake_tool(name):
    """실제 LangChain 도구(bind_tools/ToolNode 호환) — 그래프 컴파일만 하므로 no-op 본문."""
    return StructuredTool.from_function(
        func=lambda query="": "",
        name=name,
        description=f"{name} 도구",
    )


MODEL_CFG = {"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}}


def main():
    # U1 등록
    impl = get_agent_impl("pipeline")
    check(impl is not None and isinstance(impl, LinearPipelineAgent), "U1 get_agent_impl('pipeline') 적합 인스턴스")
    check("pipeline" in list_agent_impls(), "U1 list_agent_impls에 'pipeline'")
    check(classify_runtime("ui", "pipeline") == "conforming", "U1 classify_runtime(ui,pipeline)=='conforming'")
    check(classify_runtime("code", "pipeline") == "non_conforming", "U1 원격은 non_conforming(무회귀)")

    # U2 describe 정직
    m = impl.describe()
    check("nodes" in (m.consumes or ()), f"U2 consumes에 nodes (got {m.consumes})")
    check(m.supports_hil is True, "U2 supports_hil True(노드 도구 HIL 가능)")

    # U3 normalize_nodes 순수
    raw = [
        {"name": "분석", "prompt": "분석하라", "model": "gpt", "tools": ["search_documents", 123]},
        {"name": "빈", "prompt": "   "},          # 프롬프트 공백 → 제외
        "잡값",                                     # dict 아님 → 제외
        {"prompt": "이름없음"},                     # 이름 자동
    ]
    norm = normalize_nodes(raw)
    check(len(norm) == 2, f"U3 프롬프트 없는/잡 노드 제외 (2개 남음, got {len(norm)})")
    check(norm[0]["name"] == "분석" and norm[1]["name"] == "노드4", "U3 이름 보존/자동 이름(인덱스)")
    check(norm[0]["tools"] == ["search_documents"], "U3 tools 문자열만 정규화(잡값 제거)")
    check(normalize_nodes("notalist") == [] and normalize_nodes(None) == [], "U3 비리스트 → 빈 리스트")

    # U4/U5 그래프 구조 + 노드별 모델/도구
    nodes = [
        {"name": "분석", "prompt": "분석", "model_cfg": MODEL_CFG, "tools": ["search_documents"]},
        {"name": "작성", "prompt": "작성", "model_cfg": MODEL_CFG, "tools": []},
        {"name": "검토", "prompt": "검토", "model_cfg": MODEL_CFG, "tools": ["nonexistent_tool"]},
    ]
    ctx = AgentBuildContext(
        prompt="",
        model_cfg=MODEL_CFG,
        tools=[_fake_tool("search_documents"), _fake_tool("other")],
        impl_config={"nodes": nodes},
    )
    graph = impl.build_graph(ctx)
    gnodes = set(graph.get_graph().nodes)
    # 선언 노드 3개가 그래프에 + 도구 있는 노드("분석")는 __tools 노드도. "검토"의 도구는 ctx.tools에
    # 없어(권한 밖) 필터링돼 도구 노드 없음(무시 = 권한 상승 0).
    check({"분석", "작성", "검토"}.issubset(gnodes), f"U4 선언 노드 3개 그래프에 (got {gnodes})")
    check("분석__tools" in gnodes, "U5 도구 있는 노드에 ToolNode(분석__tools)")
    check("검토__tools" not in gnodes, "U5 ctx.tools 밖 도구는 무시(검토__tools 없음 = 권한 상승 0)")
    check("작성__tools" not in gnodes, "U5 도구 없는 노드는 ToolNode 없음")

    # U4 빈 노드 → 단일 패스스루(크래시 안 함)
    ctx2 = AgentBuildContext(prompt="", model_cfg=MODEL_CFG, tools=[], impl_config={"nodes": []})
    g2 = impl.build_graph(ctx2)
    check(len(g2.get_graph().nodes) >= 1, "U4 빈 노드 → 단일 패스스루(정직, 크래시 0)")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
