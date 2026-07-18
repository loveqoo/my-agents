"""런타임 해석·도구 조립·그래프 지문·회상 프록시 — chat.py에서 하강(스펙 392 P4, 순환 제거).

chat.py 파사드가 재수출하는 심볼을 chat_stream 계열·chat_approval이 **지연 import로 역참조**하던
순환(chat → chat_stream/chat_approval → chat)의 근인이 이 네 심볼이 chat.py 안에 있던 것.
제3의 모듈로 내려 의존을 단방향(chat → chat_graph_build ← chat_a2a_serve/chat_approval)으로 편다.
그래프 캐시 딕셔너리 자체는 chat.py 잔류(_graph_fingerprint는 순수 함수라 여기로).
파사드는 chat.py(재수출 계약 유지).
"""

import asyncio
import hashlib
import json

from agent.runtime import AgentConfigError, CustomAgent, DefaultUiAgent, get_agent_impl

from . import memory, runtime
from .chat_context import ChatContext, _is_remote


def resolve_agent_runtime(ctx: ChatContext) -> CustomAgent | None:
    """이 에이전트의 **in-process 런타임 구현**을 해석한다(스펙 085 + 089 폴백 교정).

    - 원격(code/external) → None: 인터페이스 미대상 → 호출측이 `_a2a_stream` fallback(지금처럼).
    - 로컬(ui) + impl 미선언 → `DefaultUiAgent`(레퍼런스 적합, 정상 default).
    - 로컬(ui) + impl 적중(적합) → 그 커스텀 에이전트.
    - 로컬(ui) + impl 선언했으나 미해결(미등록/부적합) → **`AgentConfigError` raise**(스펙 089 교정3):
      `DefaultUiAgent`로 *만회·폴백하지 않는다* — 등록/설정 실수를 default가 가리지 않게 서빙을
      거부한다. 호출측이 잡아 정직히 통보.

    `impl`은 레지스트리의 *키*일 뿐 코드가 아니다 — eval/import 경로 없음(스펙 085 §보안경계)."""
    if _is_remote(ctx.source):
        return None
    impl_key = ctx.impl
    if not impl_key:
        return DefaultUiAgent()
    inst = get_agent_impl(impl_key)
    if inst is None:
        raise AgentConfigError(impl_key)
    return inst


def _rag_tools_for(ctx: ChatContext, calls_sink: list[dict]) -> list:
    """RAG 검색 도구 목록. 기본=전체 컬렉션 단일 도구(search_documents, 무회귀). 노드형(스펙 268 P1)은
    **컬렉션별 도구**(`search_documents__<컬렉션>`, _safe_name — 265 이름 체계)를 추가로 빌드해 노드가
    컬렉션을 골라 참조한다("검색 노드는 A만, 검증 노드는 B만"). 참조 안 된 도구는 노드 필터에서 그냥
    안 쓰임(무해). 구저장 민이름(search_documents)은 전체-컬렉션 도구로 계속 해석."""
    tools: list = []
    if not ctx.rag_collections:
        return tools
    ms = ctx.rag_min_scores
    tools.append(runtime.build_rag_tool(ctx.rag_collections, calls_sink, ms))
    if ctx.nodes_resolved is not None:
        for col in ctx.rag_collections:
            tools.append(
                runtime.build_rag_tool(
                    [col],
                    calls_sink,
                    ms,
                    name=runtime._safe_name("search_documents", col["name"]),
                )
            )
    return tools


class _MemoryRecallProxy:
    """노드별 회상 프록시(스펙 268 P2, 사용자 설계) — 노드형 노드가 **각자** 회상을 조회하고, 여기서
    **키워드로 캐싱**한다(같은 키워드=캐시 반환 → 비용 자연 수렴 1회, 다른 키워드=개별 조회). 이로써
    "1회 조회→노드 매핑"과 "노드별 키워드 조회"가 한 메커니즘으로 통일된다.

    - 수명 = **한 턴**(요청) — 턴을 넘겨 캐시하면 새 기억이 안 보이므로 금지.
    - 스코프는 플랫폼이 생성 시 **고정**(RBAC — 노드가 남의 기억을 못 봄, 브로커 주입 선례).
    - 조회마다 (node, query, hits, cached)를 기록(스펙 082 — 조회 행위 계측) → trace["memoryRecalls"].
    - 반환은 **포맷된 텍스트**(format_memory_hits) — 엔진(agent 패키지)이 api 모듈에 비의존."""

    def __init__(
        self, scope: dict, mem_cfg: dict | None, default_query: str, records: list[dict]
    ) -> None:
        self._scope = dict(scope)
        self._cfg = mem_cfg
        self._default = default_query or ""
        self._cache: dict[str, tuple[str, list[dict]]] = {}  # query → (포맷 텍스트, 회상 히트)
        self.records = records

    async def __call__(self, query: str | None = None, node: str = "") -> str:
        q = (query if isinstance(query, str) and query.strip() else self._default).strip()[:300]
        if not q:
            return ""
        cached = q in self._cache
        if not cached:
            hits = await asyncio.to_thread(memory.search, self._scope, q, self._cfg)
            self._cache[q] = (memory.format_memory_hits(hits) if hits else "", hits)
        text, hits = self._cache[q]
        # 기록 쿼리는 비밀 마스킹(codex 268 P3 — 타 트레이스 표면과 정합): input 모드 키워드는 앞 노드
        # 출력이라 비밀이 섞일 수 있음(_sanitize가 sk-… 등 마스킹, 캡 120).
        self.records.append(
            {
                "node": node,
                "query": memory._sanitize(q, cap=120),
                "hits": len(hits),
                "cached": cached,
                # 회상 내용(스펙 359) — 표준 retrieve_memory 경로(t.memories)와 같은
                # {text, score, scope} 리스트로 실어 인스펙터가 MemoryRow로 렌더한다. 내용 마스킹은
                # 표준 경로와 파리티(자기 스코프 저장 기억, 이미 무마스킹 노출 — 새 노출 아님).
                "memories": hits,
            }
        )
        return text


def _graph_fingerprint(ctx: ChatContext) -> str | None:
    """캐시 적격(단순형 default)이면 빌드 결정 요소의 지문, 아니면 None(새 인스턴스 경로).

    지문 = 모델 정체(연결·model_id·params·temperature) + MCP 도구 집합(이름·**블록 버전**·auth 지문 —
    369 불변성으로 버전이 콘텐츠를 유일하게 가리킴) + 도구 필터 + 승인 정책 + RAG 배선 + 체크포인터
    유무. 비밀은 sha256 지문으로만(평문 키 저장 금지). 노드형/조율형/산출물형은 per-turn 재료(브로커·
    프록시)가 그래프에 얽혀 제외(후속). 캐시 딕셔너리는 chat.py(_GRAPH_CACHE) — 이 함수는 순수."""
    if ctx.nodes_resolved is not None or ctx.artifact_spec is not None:
        return None
    if (ctx.impl or "default") != "default":
        return None
    mc = ctx.model_cfg or {}
    if not mc:
        return None

    def _fp(text: str) -> str:
        return hashlib.sha256((text or "").encode()).hexdigest()[:12]

    blob = {
        "model": [
            mc.get("base_url"),
            _fp(mc.get("api_key") or ""),
            mc.get("model_id"),
            json.dumps(mc.get("params") or {}, sort_keys=True),
            ctx.temperature,
        ],
        "mcp": sorted(
            [s["name"], s.get("version") or 0, _fp(s.get("auth_token") or "")]
            for s in ctx.mcp_servers or []
        ),
        "tool_filter": sorted(ctx.tool_names or []),
        "policy": json.dumps(ctx.tool_policy or {}, sort_keys=True),
        "rag": _fp(json.dumps(ctx.rag_collections or [], sort_keys=True, default=str)),
        "rag_min": json.dumps(ctx.rag_min_scores or {}, sort_keys=True),
        "ckpt": not ctx.ephemeral,
    }
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()
