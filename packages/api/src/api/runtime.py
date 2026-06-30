"""에이전트 실행 런타임 — 실 MCP 도구 연결 + 트레이스 조립.

MCP 서버에 **실제로 연결**(langchain-mcp-adapters `MultiServerMCPClient`, streamable-HTTP)해
활성 도구를 LangChain 툴로 가져오고, 트레이스·HIL 승인 게이트(스펙 041)·graceful 실패 래퍼로
감싸 ReAct 루프에 넣는다. 반환값은 하드코딩한 합성 문자열이 아니라 서버가 실제로
계산한 값이다(이전 합성 캔드 응답 테이블은 폐기). stdio transport는 유예(스펙 054 §7).

지배 스펙: docs/spec/054-mcp-real-runtime-http.md (구: 007 Phase 2)
"""

import asyncio
import math
import re
import time
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt


def _safe_name(server: str, tool_name: str) -> str:
    """LLM 툴 이름 제약([A-Za-z0-9_-])에 맞게 정규화. 원래 server/tool은 트레이스에 유지."""
    raw = f"{server}__{tool_name}"
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:60]
    return safe or "tool"


# HIL 승인 게이트 정책(스펙 041) — approver=admin 권한에 묶인 (server, tool) 도구만.
# 이 도구를 ReAct가 호출하면 **실 부수효과(rt.ainvoke) 이전에** langgraph interrupt로 그래프가
# 일시정지되고, admin 승인 전에는 절대 실행되지 않는다(핵심 불변식). 정책은 코드 한 곳 — verify로 핀.
# 키는 (McpServer.name, 도구이름). seed가 이 서버/도구를 노출한다.
# "local-tools"는 mock_mcp.MOCK_MCP_SERVER_NAME — verify 테스트가 두 상수의 일치를 단언한다(drift 방지).
_APPROVAL_ACTIONS: dict[tuple[str, str], str] = {
    ("local-tools", "delete_record"): "data.delete",
}

# 실 도구 호출 전체 deadline(초). per-read 타임아웃은 전체 데드라인이 아니므로(learning 046)
# asyncio.timeout으로 호출 전체를 감싼다 — 느린/멈춘 서버가 에이전트를 무한 대기시키지 않게.
_TOOL_TIMEOUT_S = 30


def _content_text(result: Any) -> str:
    """MCP 도구 반환을 표시·트레이스용 문자열로 정규화.

    실 MCP 도구는 문자열이 아니라 content-block 리스트(`[{'type':'text','text':...}]`)를
    돌려줄 수 있다(probe로 확인). 텍스트 블록을 추출·결합하고, 그 외 타입은 str()로 폴백한다.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, (list, tuple)):
        parts: list[str] = []
        for b in result:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
            elif b is not None:
                parts.append(str(b))
        return "\n".join(p for p in parts if p)
    if result is None:
        return ""
    return str(result)


def _wrap_mcp_tool(server: str, rt: BaseTool, calls_sink: list[dict]) -> StructuredTool:
    """실 MCP 도구(rt)를 트레이스·HIL 게이트·graceful 래퍼로 감싼다.

    rt.args_schema(JSON 스키마 dict)를 그대로 보존해 LLM이 원 도구 시그니처대로 호출하게 한다.
    `_APPROVAL_ACTIONS`에 걸리는 위험 도구는 **rt.ainvoke(부수효과) 이전에 interrupt()** 로 그래프를
    멈춰 admin 승인을 받는다(스펙 041 불변식, 실 도구 위에서 재성립). 도구 실행 실패(서버 다운·
    프로토콜 오류·타임아웃)는 잡아 graceful 문자열 + calls_sink status="error"로 — 에이전트 크래시 금지.
    """
    permission = _APPROVAL_ACTIONS.get((server, rt.name))

    async def _execute(kwargs: dict, t0: float) -> str:
        # 실 부수효과: 실제 MCP 서버 도구를 호출한다. 승인됐거나 비위험 도구일 때만 도달.
        try:
            async with asyncio.timeout(_TOOL_TIMEOUT_S):
                raw = await rt.ainvoke(kwargs)
            text = _content_text(raw)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 — 도구 오류가 에이전트를 죽이지 않는다(graceful)
            text = f"도구 실행 실패({server}.{rt.name}): {type(exc).__name__}"
            status = "error"
        calls_sink.append(
            {
                "server": server,
                "tool": rt.name,
                "status": status,
                "ms": int((time.perf_counter() - t0) * 1000) + 1,
                "args": _redact_args(kwargs),  # 스펙 087: 민감 키 마스킹 전 적재(형제 표면 누출 차단)
                "result": _cap(text, _RESULT_CAP),  # 스펙 087: 무제한 적재 방어(learning 059)
            }
        )
        return text

    async def _run(**kwargs: Any) -> str:
        t0 = time.perf_counter()
        if permission is None:
            return await _execute(kwargs, t0)
        # 위험 도구: 실 부수효과 이전에 일시정지. interrupt()는 첫 호출 시 그래프를 멈추고,
        # admin이 Command(resume={"decision":...})로 재개하면 그 값을 반환한다(도구는 처음부터
        # 재실행되지만 interrupt 이전엔 부수효과가 없어 정확히 1회만 ainvoke — 스펙 041 probe로 검증).
        decision = interrupt(
            {
                "permission": permission,
                "server": server,
                "tool": rt.name,
                "action": f"{server}.{rt.name}",
                "args": _redact_args(kwargs),  # 스펙 087: Approval.args(DB 영속)·ApprovalsView로 새기 전 마스킹
                "summary": f"{server}.{rt.name} 실행 — 관리자 승인 필요",
            }
        )
        approved = isinstance(decision, dict) and decision.get("decision") == "approve"
        if not approved:
            # 거부: 부수효과 0(ainvoke·calls_sink 미emit) — 에이전트는 이 사실로 마무리.
            return "거부됨 — 관리자가 실행을 승인하지 않았습니다."
        return await _execute(kwargs, t0)

    desc = rt.description or f"{server} 서버의 {rt.name} 도구."
    if permission is not None:
        desc += " ⚠ 위험 작업: 호출 시 관리자 승인 전까지 일시정지됩니다."
    return StructuredTool.from_function(
        coroutine=_run,
        name=_safe_name(server, rt.name),
        description=desc,
        args_schema=rt.args_schema,
    )


async def build_mcp_tools(
    servers: list[dict], calls_sink: list[dict]
) -> list[StructuredTool]:
    """등록 MCP 서버에 **실제로 연결**(MultiServerMCPClient)해 활성 도구를 LangChain 툴로 만든다.

    `servers`: `_load_context`가 해석한 dict 리스트
      `{name, url, transport, enabled_tools, auth_token(복호화|None)}`.
    HTTP/streamable만 연결한다(stdio는 스펙 054 §7에서 유예). 각 URL은 연결 이전에 net_guard(스펙
    042)로 SSRF 검사 — 사설/루프백 IP는 차단하되 DB allowlist(스펙 064 `allowed_hosts`)로 dev
    mock(127.0.0.1)을 통과시킨다(루프 전 refresh로 무재시작 반영). 서버 하나가 다운/차단/프로토콜
    오류여도 그 서버만 건너뛰고 나머지는 살린다(부분 실패
    격리 — 에이전트는 계속 실행). 각 도구는 `_wrap_mcp_tool`로 트레이스·HIL·graceful 래핑된다.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient  # 지연 임포트(모듈 경량 유지)

    from . import net_guard

    await net_guard.refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064) — 루프 전 1회
    connections: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    for s in servers:
        if (s.get("transport") or "").lower() not in ("http", "streamable_http"):
            continue  # stdio 등 미지원 transport는 조용히 제외(유예)
        url = s.get("url") or ""
        try:
            net_guard.guard_url(url)
        except net_guard.SsrfBlocked:
            continue  # SSRF 차단 서버는 연결 자체를 안 함(부수효과 0)
        headers: dict[str, str] = {}
        token = s.get("auth_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        connections[s["name"]] = {
            "transport": "streamable_http",
            "url": url,
            "headers": headers or None,
            # 리다이렉트-SSRF 차단(적대 리뷰 H1): 기본 클라이언트는 3xx를 따라가 가드를 우회하고
            # 토큰을 재전송한다 → follow_redirects=False 팩토리로 fail-closed(a2a_client와 동일 정책).
            "httpx_client_factory": net_guard.mcp_http_client_factory,
        }
        meta[s["name"]] = s

    if not connections:
        return []

    client = MultiServerMCPClient(connections)
    tools: list[StructuredTool] = []
    for name, s in meta.items():
        try:
            raw_tools = await client.get_tools(server_name=name)
        except Exception:  # noqa: BLE001 — 서버 다운/프로토콜 오류는 그 서버만 스킵
            continue
        enabled = set(s.get("enabled_tools") or [])
        for rt in raw_tools:
            if enabled and rt.name not in enabled:
                continue  # enabled_tools 밖 도구는 노출 안 함(서버측 강제)
            tools.append(_wrap_mcp_tool(name, rt, calls_sink))
    return tools


# NOTE(스펙 051): 채팅 인-챗 자가기록 도구(`save_agent_knowledge` /
# build_agent_memory_tool)는 제거됐다. LLM이 도구 설명("유저 개인정보 금지")을 어기고 유저
# 개인사실을 agent_id(교차사용자) 스코프에 써서 누출시켰다(learning 031 "도구 프롬프트 ≠ 격리").
# agent_id 메모리는 이제 **어드민 저작 전용**(agents.py CRUD) — 인간 게이트만 둔다. 회상은 유지.


class RagSearchError(Exception):
    """공유 retrieval 코어(`search_collections`)의 실패를 호출자가 표현할 수 있게 분류해 올린다.

    도구(`build_rag_tool`)는 graceful 문자열 + calls_sink status="error"로, 시험 엔드포인트(스펙 072)는
    HTTP 상태로 매핑한다. `kind`로 분기, `record_label`은 calls_sink 라벨, `tool_msg`는 도구 반환 문자열.
    """

    def __init__(self, kind: str, record_label: str, tool_msg: str) -> None:
        self.kind = kind  # "empty" | "embed" | "db"
        self.record_label = record_label
        self.tool_msg = tool_msg
        super().__init__(tool_msg)


async def search_collections(
    collections: list[dict], query: str, top_k: int = 4
) -> list[dict]:
    """RAG 검색 공유 코어(스펙 037 본체, 072로 추출). 질의 임베딩 → pgvector cosine → 상위 청크.

    `build_rag_tool`(인-챗 도구, 문자열 포맷)과 `POST /collections/{cid}/search`(시험 엔드포인트, JSON)가
    **같은 코어**를 호출한다 — 평행 구현을 새로 짜면 drift나 "엔드포인트는 초록인데 채팅은 다름"이 된다.

    핵심 불변식: 질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델로** 임베딩해야 같은 벡터 공간에서
    cosine이 의미를 가진다(learning 035 — 진실원을 따른다). `RAG_EMBED_DIMS`로 컬럼 차원은 공유되지만
    모델이 다르면 공간이 달라 검색이 무의미하므로, (base_url, model_id)별로 질의 임베딩을 1회만 호출·캐시.

    `collections`: `_load_context`가 해석한 dict 리스트
    `{id, name, embed_base_url, embed_api_key(복호화됨), embed_model_id}`.
    반환: score(=1-cosine_distance) 내림차순 hit 리스트 `[{"score","filename","text"}]`(관련 0건이면 []).
    실패(빈 질의·임베딩 서버 다운·DB 오류)는 `RagSearchError`로 올린다 — 표현은 호출자가 정한다.
    """
    from sqlalchemy import select  # 지연 임포트(모듈 경량 유지)

    from . import rag_ingest
    from .db import SessionLocal
    from .models import Chunk, Document

    q = (query or "").strip()
    if not q:
        raise RagSearchError("empty", "빈 검색어", "검색어가 비어 있습니다.")
    # top_k 방어적 강제(타자검증): 비정상 값이 새어 들어와도 크래시 없이 기본 4로 폴백.
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
                    c["embed_base_url"], c["embed_api_key"], c["embed_model_id"], [q]
                )
                qvec_cache[key] = vecs[0]
    except rag_ingest.IngestError as exc:
        raise RagSearchError("embed", "임베딩 실패", f"문서 검색 실패(질의 임베딩): {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — 어떤 실패도 호출자를 죽이지 않는다
        raise RagSearchError("embed", "임베딩 예외", "문서 검색 실패(질의 임베딩 중 오류).") from exc

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
    except Exception as exc:  # noqa: BLE001 — DB/검색 오류도 RagSearchError로
        raise RagSearchError("db", "검색 예외", "문서 검색 실패(유사도 검색 중 오류).") from exc

    # 음수 유사도(cosine 거리>1 = 벡터가 반대 방향) 제거: 반-상관 청크는 '근거'가 될 수 없다.
    # 임의 임계값이 아니라 수학적 경계(직교=0)라 정상 매치(양수)는 절대 탈락하지 않는다. 양수
    # 구간의 관련도 임계 튜닝(예 0.3 미만 컷)은 recall 트레이드오프가 있어 빚으로 남긴다(타자검증).
    relevant = [h for h in hits if h[0] <= 1.0 + 1e-9]
    # 컬렉션 간 통합 정렬 후 상위 k. (동일 임베딩 모델 가정 — 다른 모델 간 dist 스케일 차는 빚:
    # 서로 다른 벡터 공간의 거리를 한 리스트로 정렬하면 순위가 의미를 잃는다. 멀티모델 컬렉션
    # 동시 사용은 비권장이며, 강제 방지/스코어 정규화는 후속 스펙으로 남긴다.)
    relevant.sort(key=lambda h: h[0])
    return [
        {"score": 1.0 - d, "filename": filename, "text": text}
        for d, filename, text in relevant[:k]
    ]


def build_rag_tool(collections: list[dict], calls_sink: list[dict]) -> StructuredTool:
    """RAG 문서 검색 도구(스펙 037). `search_collections` 코어를 호출해 결과를 문자열로 포맷한다.

    이 함수는 **얇은 포맷터**다 — 검색 로직은 `search_collections`에 있고(시험 엔드포인트와 공유),
    여기서는 도구 계약(graceful 문자열 + calls_sink 기록)만 책임진다. 실패는 코어가 `RagSearchError`로
    올리고, 도구는 그 `tool_msg`/`record_label`로 매핑해 에이전트를 죽이지 않는다.
    """
    names = ", ".join(c["name"] for c in collections)

    async def _search(query: str = "", top_k: int = 4) -> str:
        t0 = time.perf_counter()

        def _record(status: str, result: str, n: int = 0) -> None:
            calls_sink.append(
                {
                    "server": "rag",
                    "tool": "search_documents",
                    "status": status,
                    "ms": int((time.perf_counter() - t0) * 1000) + 1,
                    "args": _redact_args({"query": (query or "").strip(), "top_k": top_k}),
                    "result": _cap(result, _RESULT_CAP),  # 스펙 087 F3: 같은 sink 표면이라 result 캡 일관 적용
                    "hits": n,
                }
            )

        try:
            results = await search_collections(collections, query, top_k)
        except RagSearchError as exc:
            _record("error", exc.record_label)
            return exc.tool_msg

        if not results:
            _record("ok", "관련 결과 0건", 0)
            return "관련 문서를 찾지 못했습니다."

        lines = [f"[문서 검색 결과 {len(results)}건]"]
        for i, h in enumerate(results, 1):
            snippet = h["text"].strip().replace("\n", " ")
            if len(snippet) > 500:
                snippet = snippet[:500] + "…"
            lines.append(f"{i}. ({h['filename']}, 유사도 {h['score']:.3f}) {snippet}")
        _record("ok", f"{len(results)}건 반환", len(results))
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


# 노드 상태 델타에서 비밀값을 띄우지 않기 위한 민감 키 패턴(닫힌 집합, 스펙 086 §2).
# 키 *이름*으로 마스킹한다 — 값 휴리스틱이 아니라(저장 크레덴셜용 crypto.is_masked와 별개).
# `[_-]key$`·`^key$`는 private_key·access_key·client_key·signing_key·encryption_key 등 *_key 비밀명을
# 포괄(codex 087 F1: api_key만으론 표준 비밀키 이름을 놓침). monkey/top_k는 구분자 없어 안 걸림.
_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|auth|credential|bearer|[_-]key$|^key$)", re.I
)
_FIELD_CAP = 300  # 필드(값) 1개 표시 상한(자)
_NODE_SUMMARY_CAP = 1200  # 노드 요약 전체 상한(자) — 필드 캡보다 커야 단일 필드가 이중 캡 안 됨
                          # (codex F3 후속: per-field 캡 후 join이 또 잘려 생략 길이가 거짓이 되던 버그)
_REDACTED = "«redacted»"


# 값 원문을 *노출해도 되는* 알려진 안전 필드(최소 allowlist). 이 기능의 존재이유가 "그 값을 보여주는
# 것"인 필드만 — 현재는 `plan`(노드가 세운 계획 텍스트)뿐. 그 외 임의 키의 문자열 값은 원문 미표시
# (fail-closed): 키 이름이 평범/비영문이라 _SENSITIVE_KEY가 못 잡아도 *값 자체* 비밀이 안 샌다
# (codex 적대 리뷰 F2: 값-비밀 차단). 새 안전 필드 추가는 "그 키는 절대 비밀이 아니다"를 보증할 때만.
_VALUE_SAFE_KEYS = frozenset({"plan"})

# 스펙 087: MCP 호출 인자·결과 redaction(형제 trace 표면). 086 노드델타와 달리 args는 *보여주는 게
# 목적*(인스펙터 디버깅 가치)이라 평범한 키의 값은 보존하고 민감 *키*만 마스킹한다(value-allowlist
# 아닌 key-blocklist — polarity가 정당하게 다름, learning 089 §3 형제 표면판). 시스템 자기 비밀은
# 이 표면에 안 온다(서버 토큰=헤더·모델 키=설정, args 아님) → defense-in-depth.
_ARG_VALUE_CAP = 500  # args 문자열 leaf 1개 표시 상한(자) — query·path 등 정상 인자 보존하되 거대값 캡
_RESULT_CAP = 2000  # 도구 결과 문자열 상한(자) — calls_sink에 무제한 적재(trace 비대) 방어(learning 059)
_REDACT_MAX_DEPTH = 6  # args 재귀 깊이 상한 — 사이클/거대 중첩 fail-closed


def _redact_args(obj: Any, _depth: int = 0) -> Any:
    """MCP 도구 인자(kwargs)를 표시·영속(calls_sink·interrupt·Approval.args) 전에 정화한다(스펙 087).

    - 민감 *키*(_SENSITIVE_KEY)의 값은 `«redacted»`로. 평범한 키의 값은 *원문 보존*(args는 사람에게
      보일 표면이라 086 노드델타와 polarity가 다름 — 디버깅 가치 유지).
    - 문자열 leaf는 _cap(_ARG_VALUE_CAP)로 budgeted 캡(raw에서, learning 059).
    - fail-closed: 비문자 키는 str(k)·깊이 상한·전체 try/except → 실패 시 안전 마커(스트림 안 깸).
    JSON 직렬화 가능한 구조만 반환(calls_sink→json.dumps·Approval.args JSONB).
    """
    try:
        if _depth > _REDACT_MAX_DEPTH:
            return "«depth-capped»"
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                key = str(k)
                out[key] = _REDACTED if _SENSITIVE_KEY.search(key) else _redact_args(v, _depth + 1)
            return out
        if isinstance(obj, (list, tuple)):
            return [_redact_args(v, _depth + 1) for v in obj]
        if isinstance(obj, str):
            return _cap(obj, _ARG_VALUE_CAP)
        if isinstance(obj, float):
            # NaN/Infinity는 JSONB(Approval.args)·JSON 직렬화에 비유효 → 안전 마커로(codex 087 F2 fail-closed).
            return obj if math.isfinite(obj) else f"<{obj}>"
        if obj is None or isinstance(obj, (bool, int)):
            return obj  # 스칼라(유한 길이, 비밀 위험 낮음)
        return f"<{type(obj).__name__}>"  # 미지 타입은 타입명만(fail-closed)
    except Exception:  # noqa: BLE001 — redaction 실패가 도구/스트림을 깨면 안 됨(fail-closed)
        return "«redact-failed»"


def _cap(s: str, limit: int = _NODE_SUMMARY_CAP) -> str:
    """raw 문자열에서 캡 — 초과분은 정직 표기(no silent truncation). 원문 길이(`len(s)`=O(1))로 표기하되
    복사는 `s[:limit]`만(budgeted) — 거대 문자열을 통째 다시 만들지 않는다(codex F3: post-build cap 금지)."""
    if len(s) <= limit:
        return s
    return s[:limit] + f"…({len(s) - limit}자 생략)"


def _summarize_node_update(node: str, delta: Any) -> str | None:
    """노드가 발화하며 바꾼 상태 델타를 사람이 읽을 짧은 문자열로 요약(스펙 086).

    불변식(codex 적대 리뷰 F2·F3·F5 반영):
    (1) **비밀 누출 0(fail-closed)** — 민감 *키*(_SENSITIVE_KEY)는 값 마스킹하고, 그 외 임의 키의
        문자열 값은 *원문 미표시*(길이만). 값 원문은 _VALUE_SAFE_KEYS(우리가 심은 안전 필드)만.
        키 이름이 평범/비영문이라 키-패턴이 못 잡아도 값-비밀이 안 샌다.
    (2) **budgeted 캡** — 각 값을 append 전에 _cap에 통과(거대 값을 join으로 통째 만들지 않음 —
        learning: .content 위 카운트는 막은 척, raw에서 캡).
    (3) **fail-closed 예외** — 비문자 키 등으로 요약이 실패해도 None 반환(chat loop 안 깸, F5).
    빈/무의미 델타는 None(요약 행 미표시)."""
    if not isinstance(delta, dict) or not delta:
        return None
    try:
        parts: list[str] = []
        for raw_key, val in delta.items():
            key = str(raw_key)  # F5: 비문자 키도 안전하게(이후 정규식/표시 모두 str 기준).
            if _SENSITIVE_KEY.search(key):
                parts.append(f"{key}={_REDACTED}")
                continue
            # messages는 이미 토큰으로 스트림됐다 — 본문 중복 안 싣고 건수만.
            if key == "messages" and isinstance(val, list):
                parts.append(f"메시지 {len(val)}건")
                continue
            if isinstance(val, str):
                # 안전 키(plan)만 값 원문(budgeted 캡); 그 외 임의 키는 길이만(F2 값-비밀 fail-closed).
                if key in _VALUE_SAFE_KEYS:
                    parts.append(_cap(val, _FIELD_CAP))  # 필드 캡(노드 전체 캡보다 작음 — 이중 캡 방지)
                else:
                    parts.append(f"{key}: <{len(val)}자>")
            elif isinstance(val, (list, tuple)):
                parts.append(f"{key}[{len(val)}]")
            elif isinstance(val, dict):
                # 중첩 dict도 키만(중첩 안의 비밀 누출 차단 — 값 펼치지 않음). 키 목록도 캡(거대 dict 방어).
                inner = _cap(
                    ", ".join(_REDACTED if _SENSITIVE_KEY.search(str(k)) else str(k) for k in val), 80
                )
                parts.append(f"{key}{{{inner}}}")
            elif val is None or isinstance(val, (bool, int, float)):
                parts.append(f"{key}={val}")  # 스칼라(유한 길이, 비밀 위험 낮음)
            else:
                parts.append(f"{key}=<{type(val).__name__}>")  # 미지 타입은 타입명만(fail-closed)
        text = _cap(" · ".join(p for p in parts if p))
        return text or None
    except Exception:  # noqa: BLE001 — 요약 실패가 스트림을 깨면 안 됨(F5 fail-closed)
        return None


def _timeline_from_observations(observed: list[dict]) -> list[dict]:
    """관측 레코드(`{node, ms, summary}`, 스펙 086)를 인스펙터 타임라인으로. ms는 실측(균등분할
    아님), summary는 안전 요약. __start__/__end__ 센티넬로 감싸 표시 일관성 유지. 중복(재진입) 보존."""
    path: list[dict] = [{"node": "__start__", "ms": 0}]
    for rec in observed:
        item = {"node": rec["node"], "ms": int(rec.get("ms", 0))}
        if rec.get("summary"):
            item["summary"] = rec["summary"]
        # 병렬 superstep(한 update 청크에 노드 2+)이면 ms는 *공유 청크 경과*지 노드별 실측이 아니다 —
        # 순차 누적으로 과장 표시되지 않게 플래그를 싣는다(codex F4: ms 정직성).
        if rec.get("parallel"):
            item["parallel"] = True
        path.append(item)
    path.append({"node": "__end__", "ms": 15})
    return path


def _timeline_from_nodes(nodes: list[str], total_ms: int) -> list[dict]:
    """`updates` 스트림서 **관측한 노드 발화 순서**로 타임라인을 구성(스펙 085).

    하드코딩 합성(build_graph_path)과 달리 어떤 적합 그래프든 자기 실 노드를 그대로 싣는다 —
    create_agent(단일 노드)든 plan→execute(다노드)든. 중복은 보존(같은 노드 반복 발화=실 재진입).
    __start__/__end__ 센티넬로 감싸 인스펙터 표시 일관성 유지.

    경계(codex 적대 리뷰 F3): 이건 **관측된 update 순서**지 엄밀한 호출 스택 순서가 아니다.
    *직렬* 그래프(현 출하 2종: create_agent ReAct, plan→execute)에선 update가 노드별 순차
    도착이라 실행 순서와 일치한다. 하지만 *병렬 superstep* 그래프라면 한 update 청크가 여러
    분기 노드를 동시에 실어와 dict 키 순서로 평탄화되므로 — 실행에 전순서가 없을 수 있고 — 이
    타임라인은 근사다. ms도 total을 노드 수로 **균등 분할**한 표시용 추정치지 노드별 실측이
    아니다. 병렬 그래프를 1급 추적하려면 superstep 그룹핑·노드별 실측 타이밍을 싣는 스트림
    소스로 승급해야 한다(후속 스펙)."""
    seq = [n for n in nodes if not n.startswith("__")]
    per = int(total_ms / max(1, len(seq)))
    path: list[dict] = [{"node": "__start__", "ms": 0}]
    for n in seq:
        path.append({"node": n, "ms": per})
    path.append({"node": "__end__", "ms": 15})
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
    graph_nodes: list[str] | None = None,
    graph_observations: list[dict] | None = None,
) -> dict[str, Any]:
    """Playground 인스펙터가 기대하는 트레이스 형태로 조립.

    타임라인 우선순위(무회귀 — 셋 다 보존):
      1. graph_observations(`{node, ms, summary}` 실측·요약, 스펙 086) — 풀디테일.
      2. graph_nodes(실 노드열 순서만, 스펙 085) — 요약/실측 없는 경로(현 폴백 호출부 호환).
      3. build_graph_path(합성) — 원격 재개 등 노드 관측 불가 시."""
    if graph_observations:
        graph = _timeline_from_observations(graph_observations)
    elif graph_nodes:
        graph = _timeline_from_nodes(graph_nodes, total_ms)
    else:
        graph = build_graph_path(used_memory, bool(mcp_calls), total_ms)
    return {
        "latencyMs": total_ms,
        "tokens": tokens,
        "promptRef": agent_id,
        "memories": memories,
        "mcp": mcp_calls,
        "graph": graph,
    }
