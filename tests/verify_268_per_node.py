"""verify_268 (단위) — 노드별 RAG(컬렉션별 도구) + 캐싱 회상 프록시 (스펙 268).

  P1 컬렉션별 도구: build_rag_tool(name=...)이 도구명·sink 기록에 반영 / _rag_tools_for가 노드형이면
     전체 1개+컬렉션별 N개, 비노드형이면 1개만(무회귀).
  P2 프록시: 같은 키워드 2회 → 실검색 1회+2번째 cached=True / 다른 키워드 → 실검색 2회 /
     빈 키워드 → 빈 문자열·기록 없음 / 기본 키워드(user) 폴백 / 스코프 고정(생성 시 복사).
  P2 엔진: memories 있는 노드만 프록시 호출(첫 진입) / memoryQuery=input이면 노드 입력을 키워드로 /
     회상 텍스트가 그 노드 시스템 프롬프트에만 덧붙음 / 프록시 예외 → 노드 생존(graceful).
  스키마: memories/memoryQuery 화이트리스트 왕복.

실행: uv run --project packages/api python tests/verify_268_per_node.py
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
    if cond:
        passed += 1
    else:
        _fails.append(msg)


MODEL_CFG = {"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}}
COLS = [
    {
        "id": 1,
        "name": "docs-kb",
        "embed_base_url": "http://x",
        "embed_api_key": "k",
        "embed_model_id": "e",
    },
    {
        "id": 2,
        "name": "team-notes",
        "embed_base_url": "http://x",
        "embed_api_key": "k",
        "embed_model_id": "e",
    },
]


async def main():
    # ── P1: build_rag_tool name 파라미터 + _rag_tools_for 분기 ──
    import uuid

    from api import runtime as api_runtime
    from api.chat import ChatContext, _MemoryRecallProxy, _rag_tools_for

    sink: list = []
    t = api_runtime.build_rag_tool([COLS[0]], sink, None, name="search_documents__docs-kb")
    check(t.name == "search_documents__docs-kb", "P1 build_rag_tool name 파라미터 반영")
    t2 = api_runtime.build_rag_tool(COLS, sink, None)
    check(t2.name == "search_documents", "P1 기본 이름 무회귀(search_documents)")

    ctx_pipe = ChatContext(
        agent_pk=uuid.uuid4(), rag_collections=COLS, nodes_resolved=[{"name": "n"}]
    )
    tools = _rag_tools_for(ctx_pipe, sink)
    names = [x.name for x in tools]
    check(
        names == ["search_documents", "search_documents__docs-kb", "search_documents__team-notes"],
        f"P1 노드형=전체 1 + 컬렉션별 N (got {names})",
    )
    ctx_plain = ChatContext(agent_pk=uuid.uuid4(), rag_collections=COLS, nodes_resolved=None)
    names2 = [x.name for x in _rag_tools_for(ctx_plain, sink)]
    check(names2 == ["search_documents"], f"P1 비노드형=단일 도구만(무회귀) (got {names2})")

    # ── P2: 프록시 캐싱(실검색 카운트는 memory.search 몽키패치) ──
    from api import chat as chat_mod

    calls = []
    orig_search = chat_mod.memory.search
    orig_format = chat_mod.memory.format_memory_hits
    chat_mod.memory.search = lambda scope, q, cfg: (
        calls.append((dict(scope), q)) or [{"memory": f"hit:{q}"}]
    )
    chat_mod.memory.format_memory_hits = lambda hits: " / ".join(h["memory"] for h in hits)
    try:
        rec: list = []
        proxy = _MemoryRecallProxy(
            {"user_id": "u1", "run_id": "s1"}, {"cfg": 1}, "사용자 질문", rec
        )
        r1 = await proxy(None, node="A")  # 기본 키워드(user)
        r2 = await proxy(None, node="B")  # 같은 키워드 → 캐시
        r3 = await proxy("노드 입력", node="C")  # 다른 키워드 → 실검색
        check(len(calls) == 2, f"P2 같은 키워드=실검색 1회·다른 키워드=+1 (실검색 {len(calls)}회)")
        check(
            rec[0]["cached"] is False and rec[1]["cached"] is True and rec[2]["cached"] is False,
            f"P2 cached 플래그 (got {[r['cached'] for r in rec]})",
        )
        check(
            r1 == r2 == "hit:사용자 질문" and r3 == "hit:노드 입력",
            "P2 캐시 반환값 동일·키워드별 상이",
        )
        check([r["node"] for r in rec] == ["A", "B", "C"], "P2 노드 귀속 기록")
        check(calls[0][0] == {"user_id": "u1", "run_id": "s1"}, "P2 스코프 고정(생성 시 값 그대로)")
        r4 = await proxy("   ", node="D")  # 공백 키워드 = None과 동일(기본 키워드 폴백, 캐시 히트)
        check(
            r4 == "hit:사용자 질문" and rec[3]["cached"] is True,
            "P2 공백 키워드→기본 폴백(캐시 공유)",
        )
        # ── 스펙 359: record가 회상 내용(memories)을 실어 인스펙터가 표준 경로처럼 렌더 ──
        check(all("memories" in r for r in rec), "359 전 record가 memories 필드 보유")
        check(
            rec[0]["memories"] == [{"memory": "hit:사용자 질문"}],
            f"359 record에 회상 히트 실림 (got {rec[0].get('memories')})",
        )
        check(all(r["hits"] == len(r["memories"]) for r in rec), "359 hits 카운트 = memories 길이")
        # 캐시 공유 행(cached=True)도 내용 자기완결 — 노드별 "무엇을 읽었나" 온전
        check(
            rec[1]["cached"] is True and rec[1]["memories"] == [{"memory": "hit:사용자 질문"}],
            "359 캐시 공유 행도 회상 내용 보유(노드 자기완결)",
        )
        check(
            rec[2]["memories"] == [{"memory": "hit:노드 입력"}], "359 키워드별 다른 내용 정확 귀속"
        )
        # 빈 기본 키워드 프록시(재개 등) — 빈 조회는 기록 자체를 안 남김
        proxy2 = _MemoryRecallProxy({}, {"cfg": 1}, "", [])
        check(await proxy2(None, node="E") == "", "P2 기본 키워드 없음 → 빈 문자열(무해)")
    finally:
        chat_mod.memory.search = orig_search
        chat_mod.memory.format_memory_hits = orig_format

    # ── P2 엔진: 노드별 회상 주입(첫 진입·선택 노드만·input 모드) ──
    from agent.runtime import AgentBuildContext
    import agent.flows.pipeline as P
    from agent.flows.pipeline import LinearPipelineAgent

    seen_sys = []  # (프롬프트 키, 시스템 프롬프트 전문)
    orig_model = P._model_from_node

    def fake_model(node, ctx):
        class _F:
            def bind_tools(self, tools):
                return self

            async def ainvoke(self, messages):
                seen_sys.append((node["prompt"], messages[0].content))
                return AIMessage(content=f"OUT[{node['prompt']}]")

        return _F()

    P._model_from_node = fake_model
    try:
        prox_calls = []

        async def fake_recall(query=None, node=""):
            prox_calls.append({"query": query, "node": node})
            return "회상된 사실 X"

        nodes = [
            {
                "name": "n1",
                "prompt": "P1",
                "model_cfg": MODEL_CFG,
                "tools": [],
                "memories": ["장기 기억 (mem0)"],
            },
            {"name": "n2", "prompt": "P2", "model_cfg": MODEL_CFG, "tools": []},  # 기억 미선택
            {
                "name": "n3",
                "prompt": "P3",
                "model_cfg": MODEL_CFG,
                "tools": [],
                "memories": ["장기 기억 (mem0)"],
                "memoryQuery": "input",
            },
        ]
        ctx = AgentBuildContext(
            prompt="",
            model_cfg=MODEL_CFG,
            tools=[],
            impl_config={"nodes": nodes},
            memory_recall=fake_recall,
        )
        out = (
            await LinearPipelineAgent()
            .build_graph(ctx)
            .ainvoke({"messages": [HumanMessage(content="USER_IN")]})
        )
        sys_of = {k: v for k, v in seen_sys}
        check("회상된 사실 X" in sys_of["P1"], "엔진: 기억 선택 노드(n1) 프롬프트에 회상 블록")
        check("회상된 사실 X" not in sys_of["P2"], "엔진: 미선택 노드(n2)엔 회상 없음")
        check("회상된 사실 X" in sys_of["P3"], "엔진: n3(input 모드)에도 회상 블록")
        check(
            prox_calls[0]["query"] is None and prox_calls[0]["node"] == "n1",
            "엔진: user 모드=기본 키워드(None)",
        )
        check(
            prox_calls[1]["query"] == "OUT[P2]" and prox_calls[1]["node"] == "n3",
            f"엔진: input 모드=노드가 받은 마지막 메시지 (got {prox_calls[1]})",
        )
        check(len(prox_calls) == 2, f"엔진: 프록시 호출 2회(선택 노드만) (got {len(prox_calls)})")

        # 프록시 예외 → 노드 생존
        async def boom(query=None, node=""):
            raise RuntimeError("mem down")

        ctx2 = AgentBuildContext(
            prompt="",
            model_cfg=MODEL_CFG,
            tools=[],
            impl_config={"nodes": [nodes[0]]},
            memory_recall=boom,
        )
        out2 = (
            await LinearPipelineAgent()
            .build_graph(ctx2)
            .ainvoke({"messages": [HumanMessage(content="X")]})
        )
        check(len(out2["messages"]) == 2, "엔진: 프록시 예외에도 노드 생존(graceful)")
    finally:
        P._model_from_node = orig_model

    # ── codex 268 후속: __tools 이름 충돌 회피 + 기록 쿼리 마스킹 ──
    from langchain_core.tools import StructuredTool

    probe = StructuredTool.from_function(func=lambda query="": "", name="probe", description="p")
    P._model_from_node = fake_model
    try:
        # 노드 "A"(도구 있음) + 노드 "A__tools"(문자 그대로) → 크래시 없이 빌드·id 회피
        nodes_clash = [
            {"name": "A", "prompt": "PA", "model_cfg": MODEL_CFG, "tools": ["probe"]},
            {"name": "A__tools", "prompt": "PB", "model_cfg": MODEL_CFG, "tools": []},
        ]
        ctx3 = AgentBuildContext(
            prompt="", model_cfg=MODEL_CFG, tools=[probe], impl_config={"nodes": nodes_clash}
        )
        g3 = LinearPipelineAgent().build_graph(ctx3)
        g3nodes = set(g3.get_graph().nodes)
        check(
            "A" in g3nodes and "A__tools" in g3nodes and "A__tools_" in g3nodes,
            f"P2 예약 접미: A의 도구 노드(A__tools)와 사용자 노드(A__tools→A__tools_) 공존 (got {sorted(g3nodes)})",
        )
    finally:
        P._model_from_node = orig_model

    chat_mod.memory.search = lambda scope, q, cfg: [{"memory": "m"}]
    chat_mod.memory.format_memory_hits = lambda hits: "m"
    try:
        rec2: list = []
        proxy3 = _MemoryRecallProxy({}, {"cfg": 1}, "기본", rec2)
        await proxy3("비밀 sk-abcdef1234567890 포함 키워드", node="N")
        check(
            "sk-abcdef1234567890" not in rec2[0]["query"],
            f"P3 기록 쿼리 비밀 마스킹 (got {rec2[0]['query']})",
        )
    finally:
        chat_mod.memory.search = orig_search
        chat_mod.memory.format_memory_hits = orig_format

    # ── 스키마: memories/memoryQuery 화이트리스트 ──
    from api.schemas import AgentConfig

    n = AgentConfig(
        nodes=[
            {"prompt": "p", "memories": ["장기 기억 (mem0)", 3], "memoryQuery": "input", "evil": 1}
        ]
    ).nodes
    check(
        n[0].get("memories") == ["장기 기억 (mem0)"]
        and n[0].get("memoryQuery") == "input"
        and "evil" not in n[0],
        f"스키마: memories/memoryQuery 보존·잡 원소·임의 키 드롭 (got {n[0]})",
    )
    n2 = AgentConfig(nodes=[{"prompt": "p", "memoryQuery": "hacker"}]).nodes
    check("memoryQuery" not in n2[0], "스키마: memoryQuery 잡값 드롭")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
