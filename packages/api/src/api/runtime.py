"""에이전트 실행 런타임 — 합성 MCP 툴 + 트레이스 조립.

v1: 실제 MCP 연결(langchain-mcp-adapters) 대신, 에이전트가 선택한 MCP 서버의
활성 툴마다 '합성 툴'을 만들어 ReAct 루프가 호출·기록할 수 있게 한다(트레이스 확인용).
실제 MCP 연결은 이후 루프.

지배 스펙: docs/spec/007-real-agent-service.md (Phase 2)
"""

import re
import time
from typing import Any, Callable

from langchain_core.tools import StructuredTool


def _safe_name(server: str, tool_name: str) -> str:
    """LLM 툴 이름 제약([A-Za-z0-9_-])에 맞게 정규화. 원래 server/tool은 트레이스에 유지."""
    raw = f"{server}__{tool_name}"
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:60]
    return safe or "tool"

# 합성 툴이 돌려주는 서버별 결과 문구 (모의).
_CANNED = {
    "tavily": "검색 결과 5건 (모의)",
    "filesystem": "파일 내용 (모의, 2.1KB)",
    "github": "PR/파일 메타 (모의)",
    "prometheus": "12 series (모의)",
    "kubernetes": "리소스 상태 (모의)",
    "gcal": "이벤트 목록 (모의)",
    "gmail": "메일 검색 결과 (모의)",
    "notion": "append ok (모의)",
}


def build_tools(
    mcp_pairs: list[tuple[str, str]], calls_sink: list[dict]
) -> list[StructuredTool]:
    """(server, tool) 목록 → 합성 LangChain 툴. 호출 시 calls_sink에 트레이스 기록."""
    tools: list[StructuredTool] = []
    for server, tool_name in mcp_pairs:

        def _make(server: str, tool_name: str) -> Callable[[str], str]:
            def _run(query: str = "") -> str:
                t0 = time.perf_counter()
                result = _CANNED.get(server, "ok (모의)")
                calls_sink.append(
                    {
                        "server": server,
                        "tool": tool_name,
                        "status": "ok",
                        "ms": int((time.perf_counter() - t0) * 1000) + 1,
                        "args": {"query": query},
                        "result": result,
                    }
                )
                return result

            return _run

        tools.append(
            StructuredTool.from_function(
                func=_make(server, tool_name),
                name=_safe_name(server, tool_name),
                description=f"{server} 서버의 {tool_name} 도구 (모의). 입력: query 문자열.",
            )
        )
    return tools


def build_agent_memory_tool(
    ext_agent_id: str, mem_cfg: dict | None, calls_sink: list[dict]
) -> StructuredTool:
    """에이전트 자가기록 도구(스펙 029). 호출 시 agent_id-only·infer=False로 mem0에 저장.

    누출 안전: **agent_id만** 태깅(user_id·run_id 안 붙임) → 특정 유저 메모리 오염 0. 도구 설명으로
    '재사용 가능한 일반 지식만, 지금 대화 중인 유저 개인정보는 금지'를 규율한다. 자동추출이 아니라
    에이전트가 의도적으로 호출할 때만 발생하는 게 핵심(스펙 020 누출 차단의 '의도적 쓰기 채널').
    """
    from . import memory  # 지연 임포트(순환 회피)

    def _save(fact: str = "") -> str:
        t0 = time.perf_counter()
        fact = (fact or "").strip()
        if not fact:
            return "저장할 사실이 비어 있습니다."
        memory.add(
            {"agent_id": ext_agent_id},
            [{"role": "user", "content": fact}],
            mem_cfg,
            infer=False,
        )
        calls_sink.append(
            {
                "server": "memory",
                "tool": "save_agent_knowledge",
                "status": "ok",
                "ms": int((time.perf_counter() - t0) * 1000) + 1,
                "args": {"fact": fact},
                "result": "saved (agent 전용)",
            }
        )
        return "에이전트 전용 기억으로 저장했습니다."

    return StructuredTool.from_function(
        func=_save,
        name="save_agent_knowledge",
        description=(
            "이 에이전트가 앞으로 재사용할 **일반 지식**(역할·도메인·절차·선호 등)을 자신의 전용 "
            "기억에 저장한다. 지금 대화 중인 특정 사용자에 대한 개인정보·사실은 절대 저장하지 말 것"
            "(그건 사용자 메모리에 자동 저장된다). 입력: fact(저장할 한 줄 사실)."
        ),
    )


def build_graph_path(used_memory: bool, used_tools: bool, total_ms: int) -> list[dict]:
    """관측된 실행으로 LangGraph 경로 트레이스를 합성. 인스펙터 표시용."""
    nodes = ["__start__"]
    if used_memory:
        nodes.append("retrieve_memory")
    if used_tools:
        nodes.append("tools")
    nodes.append("call_model")
    nodes.append("__end__")
    # total_ms를 노드에 대략 분배 (start/end는 0/소량).
    inner = [n for n in nodes if not n.startswith("__")]
    per = int(total_ms / max(1, len(inner)))
    path: list[dict] = []
    for n in nodes:
        if n == "__start__":
            path.append({"node": n, "ms": 0})
        elif n == "__end__":
            path.append({"node": n, "ms": 15})
        else:
            path.append({"node": n, "ms": per})
    return path


def estimate_tokens(prompt_chars: int, output_chars: int) -> dict[str, int]:
    """대략적 토큰 추정 (≈4 chars/token). usage가 없을 때 폴백."""
    return {"in": max(1, prompt_chars // 4), "out": max(1, output_chars // 4)}


def assemble_trace(
    *,
    agent_id: str,
    memories: list[dict],
    mcp_calls: list[dict],
    used_memory: bool,
    total_ms: int,
    tokens: dict[str, int],
) -> dict[str, Any]:
    """Playground 인스펙터가 기대하는 트레이스 형태로 조립."""
    return {
        "latencyMs": total_ms,
        "tokens": tokens,
        "promptRef": agent_id,
        "memories": memories,
        "mcp": mcp_calls,
        "graph": build_graph_path(used_memory, bool(mcp_calls), total_ms),
    }
