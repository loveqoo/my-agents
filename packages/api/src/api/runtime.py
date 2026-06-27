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
from langgraph.types import interrupt


def _safe_name(server: str, tool_name: str) -> str:
    """LLM 툴 이름 제약([A-Za-z0-9_-])에 맞게 정규화. 원래 server/tool은 트레이스에 유지."""
    raw = f"{server}__{tool_name}"
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:60]
    return safe or "tool"


# HIL 승인 게이트 정책(스펙 041) — approver=admin 권한에 묶인 (server, tool) 도구만.
# 이 도구를 ReAct가 호출하면 부수효과(canned+calls_sink) **이전에** langgraph interrupt로 그래프가
# 일시정지되고, admin 승인 전에는 절대 실행되지 않는다(핵심 불변식). 정책은 코드 한 곳 — verify로 핀.
# 키는 _load_context의 mcp_pairs 포맷(McpServer.name, enabled_tool) 그대로. seed가 이 도구들을 노출.
_APPROVAL_ACTIONS: dict[tuple[str, str], str] = {
    ("github", "merge_pr"): "repo.merge",
    ("kubernetes", "scale"): "k8s.write",
}

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
    """(server, tool) 목록 → 합성 LangChain 툴. 호출 시 calls_sink에 트레이스 기록.

    `_APPROVAL_ACTIONS`에 걸리는 위험 도구는 **부수효과 이전에 interrupt()** 로 그래프를 멈춰
    admin 승인을 받는다(스펙 041). interrupt는 checkpointer가 있어야 동작하므로, 무체크포인터
    경로에서 위험 도구가 호출되면 그래프가 멈출 수 없어 GraphInterrupt가 예외로 샐 수 있다 —
    chat.py는 위험 도구를 가진 에이전트엔 항상 checkpointer를 붙인다(없으면 게이트 미적용 폴백).
    """
    tools: list[StructuredTool] = []
    for server, tool_name in mcp_pairs:
        permission = _APPROVAL_ACTIONS.get((server, tool_name))

        def _make(server: str, tool_name: str, permission: str | None) -> Callable[[str], str]:
            def _execute(query: str, t0: float) -> str:
                # 실 부수효과(합성: canned 반환 + calls_sink 트레이스). 승인된 뒤에만 도달.
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

            def _run(query: str = "") -> str:
                t0 = time.perf_counter()
                if permission is None:
                    return _execute(query, t0)
                # 위험 도구: 부수효과 이전에 일시정지. interrupt()는 첫 호출 시 그래프를 멈추고,
                # admin이 Command(resume={"decision":...})로 재개하면 그 값을 반환한다(도구는 처음부터
                # 재실행되지만 interrupt 이전엔 부수효과가 없어 정확히 1회만 실행 — probe로 검증).
                decision = interrupt(
                    {
                        "permission": permission,
                        "server": server,
                        "tool": tool_name,
                        "action": f"{server}.{tool_name}",
                        "args": {"query": query},
                        "summary": f"{server}.{tool_name} 실행 — 관리자 승인 필요",
                    }
                )
                approved = isinstance(decision, dict) and decision.get("decision") == "approve"
                if not approved:
                    # 거부: 부수효과 0(canned·calls_sink 미emit) — 에이전트는 이 사실로 마무리.
                    return "거부됨 — 관리자가 실행을 승인하지 않았습니다."
                return _execute(query, t0)

            return _run

        desc = f"{server} 서버의 {tool_name} 도구 (모의). 입력: query 문자열."
        if permission is not None:
            desc += " ⚠ 위험 작업: 호출 시 관리자 승인 전까지 일시정지됩니다."
        tools.append(
            StructuredTool.from_function(
                func=_make(server, tool_name, permission),
                name=_safe_name(server, tool_name),
                description=desc,
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


def build_rag_tool(collections: list[dict], calls_sink: list[dict]) -> StructuredTool:
    """RAG 문서 검색 도구(스펙 037). 모델이 호출하면 질의 임베딩 → pgvector cosine 검색 → 상위 청크.

    핵심 불변식: 질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델로** 임베딩해야 같은 벡터 공간에서
    cosine이 의미를 가진다(learning 035 — 진실원을 따른다). `RAG_EMBED_DIMS`로 컬럼 차원은 공유되지만
    모델이 다르면 공간이 달라 검색이 무의미하므로, (base_url, model_id)별로 질의 임베딩을 1회만 호출·캐시.

    `collections`: `_load_context`가 해석한 dict 리스트
    `{id, name, embed_base_url, embed_api_key(복호화됨), embed_model_id}`.
    실패(임베딩 서버 다운·DB 오류)는 잡아 graceful 문자열 + calls_sink status="error"로 — 에이전트 크래시 금지.
    """
    from sqlalchemy import select  # 지연 임포트(모듈 경량 유지)

    from . import rag_ingest
    from .db import SessionLocal
    from .models import Chunk, Document

    names = ", ".join(c["name"] for c in collections)

    async def _search(query: str = "", top_k: int = 4) -> str:
        t0 = time.perf_counter()
        query = (query or "").strip()

        def _record(status: str, result: str, n: int = 0) -> None:
            calls_sink.append(
                {
                    "server": "rag",
                    "tool": "search_documents",
                    "status": status,
                    "ms": int((time.perf_counter() - t0) * 1000) + 1,
                    "args": {"query": query, "top_k": top_k},
                    "result": result,
                    "hits": n,
                }
            )

        if not query:
            _record("error", "빈 검색어")
            return "검색어가 비어 있습니다."
        # top_k 방어적 강제(타자검증): 타입힌트로 LLM 인자는 보통 int로 강제되지만, 비정상 값이
        # 새어 들어와도 _record 이전에 크래시하지 않게 직접 흡수한다(기본 4로 폴백).
        try:
            k = max(1, min(int(top_k), 10))
        except (TypeError, ValueError):
            k = 4

        # (base_url, model_id)별 질의 임베딩 캐시 — 같은 모델을 쓰는 컬렉션은 1회만 호출.
        qvec_cache: dict[tuple[str, str], list[float]] = {}
        try:
            for c in collections:
                key = (c["embed_base_url"], c["embed_model_id"])
                if key not in qvec_cache:
                    vecs = await rag_ingest.embed_texts(
                        c["embed_base_url"], c["embed_api_key"], c["embed_model_id"], [query]
                    )
                    qvec_cache[key] = vecs[0]
        except rag_ingest.IngestError as exc:
            _record("error", "임베딩 실패")
            return f"문서 검색 실패(질의 임베딩): {exc}"
        except Exception:  # noqa: BLE001 — 어떤 실패도 에이전트를 죽이지 않는다
            _record("error", "임베딩 예외")
            return "문서 검색 실패(질의 임베딩 중 오류)."

        # 컬렉션별 cosine 검색 → 통합. 각 행: (dist, filename, text). dist 오름차순 = 가까움.
        hits: list[tuple[float, str, str]] = []
        try:
            async with SessionLocal() as db:
                for c in collections:
                    qvec = qvec_cache[(c["embed_base_url"], c["embed_model_id"])]
                    dist = Chunk.embedding.cosine_distance(qvec).label("dist")
                    rows = (
                        await db.execute(
                            select(Chunk.text, Document.filename, dist)
                            .join(Document, Chunk.document_id == Document.id)
                            .where(Chunk.collection_id == c["id"])
                            .order_by(dist)
                            .limit(k)
                        )
                    ).all()
                    for text, filename, d in rows:
                        hits.append((float(d), filename or "(파일 미상)", text))
        except Exception:  # noqa: BLE001 — DB/검색 오류도 graceful
            _record("error", "검색 예외")
            return "문서 검색 실패(유사도 검색 중 오류)."

        # 음수 유사도(cosine 거리>1 = 벡터가 반대 방향) 제거: 반-상관 청크는 '근거'가 될 수 없다.
        # 임의 임계값이 아니라 수학적 경계(직교=0)라 정상 매치(양수)는 절대 탈락하지 않는다. 양수
        # 구간의 관련도 임계 튜닝(예 0.3 미만 컷)은 recall 트레이드오프가 있어 빚으로 남긴다(타자검증).
        relevant = [h for h in hits if h[0] <= 1.0 + 1e-9]
        if not relevant:
            _record("ok", "관련 결과 0건", 0)
            return "관련 문서를 찾지 못했습니다."

        # 컬렉션 간 통합 정렬 후 상위 k. (동일 임베딩 모델 가정 — 다른 모델 간 dist 스케일 차는 빚:
        # 서로 다른 벡터 공간의 거리를 한 리스트로 정렬하면 순위가 의미를 잃는다. 멀티모델 컬렉션
        # 동시 사용은 비권장이며, 강제 방지/스코어 정규화는 후속 스펙으로 남긴다.)
        relevant.sort(key=lambda h: h[0])
        top = relevant[:k]
        lines = [f"[문서 검색 결과 {len(top)}건]"]
        for i, (d, filename, text) in enumerate(top, 1):
            snippet = text.strip().replace("\n", " ")
            if len(snippet) > 500:
                snippet = snippet[:500] + "…"
            lines.append(f"{i}. ({filename}, 유사도 {1 - d:.3f}) {snippet}")
        _record("ok", f"{len(top)}건 반환", len(top))
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_search,
        name="search_documents",
        description=(
            f"등록된 문서 컬렉션({names})에서 관련 구절을 의미(semantic) 검색한다. 사용자의 질문이 "
            "특정 문서·지식베이스의 내용을 요구하면 **답하기 전에 먼저** 이 도구로 근거 구절을 찾아라. "
            "입력: query(검색할 질문/키워드), top_k(가져올 구절 수, 기본 4)."
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
