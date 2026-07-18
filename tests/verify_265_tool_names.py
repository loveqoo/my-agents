"""verify_265 (단위) — 노드 도구 이름 해석: 정확 일치 + 무모호 접미 폴백 (스펙 265).

배경(스펙 264 실측): MCP 도구 런타임 이름은 `서버__도구`(_safe_name)인데 노드가 민이름("wiki_search")을
저장하면 by_name 정확 매칭 0 → 도구 조용히 미바인딩 → 모델이 "호출한 척" 환각.

  T1 정확 일치: 런타임 이름 그대로 저장된 노드는 그 도구 바인딩.
  T2 접미 폴백(자가치유): 민이름 저장 + 접미 유일 → 매칭(ToolNode 생성).
  T3 모호 스킵(정직): 두 서버에 동명 도구 → 민이름은 스킵(아무거나 바인딩 금지).
  T4 미존재 스킵: 풀에 없는 이름은 여전히 무시(권한 상승 0, 259 U5 유지).

실행: uv run --project packages/api python tests/verify_265_tool_names.py
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "agent", "src"
    ),
)

from langchain_core.tools import StructuredTool  # noqa: E402

from agent.runtime import AgentBuildContext  # noqa: E402
from agent.flows.pipeline import LinearPipelineAgent  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _tool(name):
    return StructuredTool.from_function(
        func=lambda query="": "", name=name, description=f"{name} 도구"
    )


MODEL_CFG = {"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}}


def _graph_nodes(node_tools_decl, pool_names):
    ctx = AgentBuildContext(
        prompt="",
        model_cfg=MODEL_CFG,
        tools=[_tool(n) for n in pool_names],
        impl_config={
            "nodes": [
                {"name": "n", "prompt": "p", "model_cfg": MODEL_CFG, "tools": node_tools_decl}
            ]
        },
    )
    g = LinearPipelineAgent().build_graph(ctx)
    return set(g.get_graph().nodes)


def main():
    # T1 정확 일치(런타임 이름 저장)
    nodes = _graph_nodes(
        ["web-fetch__wiki_search"], ["web-fetch__wiki_search", "web-fetch__wiki_page"]
    )
    check("n__tools" in nodes, "T1 런타임 이름 정확 일치 → ToolNode 생성")

    # T2 접미 폴백(민이름 저장, 접미 유일)
    nodes = _graph_nodes(["wiki_search"], ["web-fetch__wiki_search", "web-fetch__wiki_page"])
    check("n__tools" in nodes, "T2 민이름+접미 유일 → 자가치유 매칭(ToolNode 생성)")

    # T3 모호 스킵(두 서버 동명 도구)
    nodes = _graph_nodes(["search"], ["srv-a__search", "srv-b__search"])
    check("n__tools" not in nodes, "T3 접미 모호(2후보) → 스킵(아무거나 바인딩 금지)")

    # T4 미존재 스킵(259 U5 유지)
    nodes = _graph_nodes(["ghost_tool"], ["web-fetch__wiki_search"])
    check("n__tools" not in nodes, "T4 풀 밖 이름 → 무시(권한 상승 0)")

    # T2b RAG 민이름(접두 없음)은 정확 일치로 그대로
    nodes = _graph_nodes(["search_documents"], ["search_documents"])
    check("n__tools" in nodes, "T2b 접두 없는 도구(search_documents)는 정확 일치")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
