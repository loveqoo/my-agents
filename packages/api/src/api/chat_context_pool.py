"""노드형 파이프라인 풀 파생 — chat_context.py에서 분할(스펙 394 P4).

derive_pipeline_pool(구 CC 14)은 **순수 파생**(_derive_pool — DB 무접촉)과 **DB 래퍼**
(derive_pipeline_pool — 이름·cfg mutate 계약 유지)로 분리(codex 자문).
파사드는 chat_context.py(재수출 계약).
"""

from collections.abc import Sequence

from sqlalchemy import select

from . import runtime
from .db import SessionLocal
from .models import Collection, McpServer
from .node_templates import resolve_node_refs


def _used_node_tools(nodes: list[dict]) -> set[str]:
    """노드들이 참조하는 도구명(접두명 srv__tool + 구저장 민이름) 합집합."""
    return {t for n in nodes for t in (n.get("tools") or []) if isinstance(t, str)}


def _server_tool_used(s: McpServer, used: set[str], bare_owners: dict[str, set[str]]) -> bool:
    """서버 도구 중 노드가 참조한 것이 있는가 — 접두명(srv__tool) 또는 전역 유일 민이름."""
    return any(
        runtime._safe_name(s.name, t) in used or (t in used and len(bare_owners.get(t) or ()) == 1)
        for t in (s.tools or [])
    )


def _mcp_pool(servers: Sequence[McpServer], used: set[str]) -> list[str]:
    """노드 참조 도구를 보유한 MCP 서버 이름 목록.

    민이름(bare, 구저장 'echo'류) 매칭은 **전역 유일할 때만**(codex 289 #4) — 같은 도구명이 여러
    서버에 있으면 모두 풀에 열려 불필요한 MCP 접속이 생긴다. 모호=제외(fail-closed — 런타임
    _resolve_tool의 모호 스킵(265)과 같은 결). 접두명(srv__tool)은 모호성이 없어 그대로."""
    bare_owners: dict[str, set[str]] = {}
    for server in servers:
        for tool in server.tools or []:
            bare_owners.setdefault(tool, set()).add(server.name)
    return [s.name for s in servers if _server_tool_used(s, used, bare_owners)]


def _doc_pool(cols: list[str], used: set[str]) -> list[str]:
    """노드 참조 문서 컬렉션 목록 — 민이름 'search_documents'는 전체 컬렉션."""
    if "search_documents" in used:
        return list(cols)
    return [c for c in cols if runtime._safe_name("search_documents", c) in used]


def _derive_pool(
    nodes: list[dict], servers: Sequence[McpServer], cols: list[str]
) -> dict[str, list]:
    """풀 합집합 계산(순수 — DB 무접촉, 스펙 394 분해): 해석된 노드들의 참조로 mcps/vectorTables/
    memories/capabilities를 파생. 규칙은 폼 derivePipelinePool과 동일(단일 의미)."""
    used = _used_node_tools(nodes)
    return {
        "mcps": _mcp_pool(servers, used),
        "vectorTables": _doc_pool(cols, used),
        "memories": sorted(
            {m for n in nodes for m in (n.get("memories") or []) if isinstance(m, str)}
        ),
        # 에이전트-호출 축 파생(스펙 318) — 노드 `tools`의 `agent__{agent_id}`에서 대상 id를 뽑아
        # capabilities(브로커 allowlist)로 심는다. 권한 비상승: 노드가 이미 참조하는 것의 합집합.
        # 자기 참조는 런타임 방문 집합(_delegable)이 최종 차단(UI도 선배제).
        "capabilities": sorted(
            {
                t[len("agent__") :]
                for t in used
                if t.startswith("agent__") and len(t) > len("agent__")
            }
        ),
    }


async def derive_pipeline_pool(cfg: dict) -> None:
    """노드형 풀 서버 파생(스펙 289 P2) — impl=pipeline이면 mcps/vectorTables/memories를 **노드 참조의
    합집합**으로 재계산해 대체한다. 폼 derivePipelinePool과 동일 규칙(단일 의미). 파생 필드는
    denormalization이라 관리자 저작 의미 없음 → merge-preserve 불요(스펙 289 근거). 이로써 폼 밖
    입구(API 생성·오버라이드)도 노드 도구가 조용히 미바인딩되지 않는다(learning 151 구조적 봉합).
    권한 비상승: 풀은 노드가 이미 참조하는 것의 합집합 — 필터 대상=합집합 자신."""
    if cfg.get("impl") != "pipeline":
        return
    nodes = [n for n in (cfg.get("nodes") or []) if isinstance(n, dict)]
    async with SessionLocal() as db:
        # 노드 참조 해석(스펙 316) — 풀 합집합은 **해석된** 노드 기준(참조 노드의 도구·기억이 조용히
        # 미바인딩되지 않게). cfg["nodes"]는 건드리지 않는다(저장본은 ref 유지 — 핀 참조가 진실원).
        # 저장 경로(생성/수정)가 이 함수를 지나므로 미해결 참조는 저장 시점에 422로 이른 실패한다.
        nodes = [n for n in await resolve_node_refs(db, nodes) if isinstance(n, dict)]
        servers = (await db.execute(select(McpServer))).scalars().all()
        cols = list((await db.execute(select(Collection.name))).scalars().all())
    cfg.update(_derive_pool(nodes, servers, cols))
