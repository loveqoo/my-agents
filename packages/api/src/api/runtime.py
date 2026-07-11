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

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt


def is_tool_message(msg: Any) -> bool:
    """도구 노드가 낸 ToolMessage(도구 원본 응답)인가 — 채팅 본문 sink에서 제외하는 단일 판정(스펙 092).

    ReAct 그래프의 stream_mode="messages"는 모델 노드의 AIMessage(Chunk)뿐 아니라 tools 노드의 ToolMessage
    (도구 실행 원본)도 청크로 흘린다(`.dev/probe_092_tool_message_stream.py`로 실측). 본문에는 모델의
    추론만 남기고 도구 원본은 빼야 하며, 도구 호출 자체는 인스펙터 trace(calls_sink)에 독립 보존된다.
    판별은 **isinstance(ToolMessage)** — `.type` 문자열은 청크/비청크 간 불안정하다(ToolMessage.type=='tool'
    이지만 ToolMessageChunk.type=='ToolMessageChunk', AIMessageChunk.type=='AIMessageChunk'로 측정됨).
    ToolMessageChunk는 ToolMessage의 서브클래스라 isinstance가 둘 다 잡고 AI 메시지는 제외한다(verify_092로 확정)."""
    return isinstance(msg, ToolMessage)


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


def resolve_tool_approval(
    server: str,
    tool: str,
    tools_meta: dict | None = None,
    tool_policy: dict | None = None,
) -> dict | None:
    """도구 승인 정책 리졸버(스펙 177) — 승인이 필요하면 `{"permission", "approver"}`, 아니면 None.

    **단일 진실원**: 그래프-tools 경로(`_wrap_mcp_tool`)와 브로커 경로
    (`broker.McpProvider.approval_for`)가 이 함수 하나를 공유한다(드리프트 0). 우선순위:
      1. **도구 기본**(P1) = `tools_meta[tool].approval` = 관리자가 데이터로 설정
         (`{required, approver?}`, approver 기본 admin). 없으면 레거시 `_APPROVAL_ACTIONS` 폴백(무회귀).
      2. **에이전트 오버라이드**(P2) = `tool_policy["mcp:{server}/{tool}"].approval`의 required/approver로
         덮음(있는 키만). 강화(끔→켬)·완화(켬→끔)·approver 변경 모두 여기서. 완화 권한 게이트는 저장
         시점(agents CRUD)에서 강제 — 리졸버는 순수 해석만.
    approver는 승인 인가에 쓰인다(`approvals._may_resolve`): admin=관리자만, self=요청 소유자 본인.
    permission 문자열은 표시·감사·레거시 하위호환용(인가는 approver 필드로 — 세그먼트 이스케이프 무관).
    """
    meta = tools_meta.get(tool) if isinstance(tools_meta, dict) else None
    base = meta.get("approval") if isinstance(meta, dict) else None
    if isinstance(base, dict):
        required = bool(base.get("required"))
        approver = base.get("approver") or "admin"
        permission = f"mcp.{server}.{tool}"
    else:  # 레거시 폴백(tools_meta에 approval 없을 때만) — delete_record 등 기존 게이트 보존.
        legacy = _APPROVAL_ACTIONS.get((server, tool))
        required = legacy is not None
        approver = "admin"
        permission = legacy or f"mcp.{server}.{tool}"
    # 에이전트 오버라이드(cap_id 규약 = capabilities와 동일 `mcp:{server}/{tool}`).
    if isinstance(tool_policy, dict):
        entry = tool_policy.get(f"mcp:{server}/{tool}")
        ov = entry.get("approval") if isinstance(entry, dict) else None
        if isinstance(ov, dict):
            if "required" in ov:
                required = bool(ov["required"])
            if ov.get("approver"):
                approver = ov["approver"]
    if not required:
        return None
    return {
        "permission": permission,
        "approver": approver if approver in ("admin", "self") else "admin",
    }


# 실 도구 호출 전체 deadline(초). per-read 타임아웃은 전체 데드라인이 아니므로(learning 046)
# asyncio.timeout으로 호출 전체를 감싼다 — 느린/멈춘 서버가 에이전트를 무한 대기시키지 않게.
_TOOL_TIMEOUT_S = 30


def _content_text(result: Any) -> str:
    """메시지/도구 content를 표시·트레이스·영속용 문자열로 정규화.

    실 MCP 도구는 물론 모델 메시지(AIMessageChunk.content)도 문자열이 아니라
    content-block 리스트(`[{'type':'text','text':...}]`)일 수 있다(probe로 확인).
    텍스트 블록을 추출·결합하고, 그 외 타입은 str()로 폴백한다. 채팅 본문 sink가
    `"".join(acc)`로 합치므로 여기서 str을 보장하지 않으면 list content가 TypeError를
    낸다 — 스펙 092 적대 검증(codex P1)이 잡은 선재 잠복 크래시를 이 정규화가 막는다."""
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


def _wrap_mcp_tool(
    server: str, rt: BaseTool, calls_sink: list[dict], approval: dict | None
) -> StructuredTool:
    """실 MCP 도구(rt)를 트레이스·HIL 게이트·graceful 래퍼로 감싼다.

    rt.args_schema(JSON 스키마 dict)를 그대로 보존해 LLM이 원 도구 시그니처대로 호출하게 한다.
    `approval`(호출부 `resolve_tool_approval`가 해석, 스펙 177 = `{permission, approver}` 또는 None)이
    non-None인 도구는 **rt.ainvoke(부수효과) 이전에 interrupt()** 로 그래프를 멈춰 승인을 받는다(스펙 041
    불변식, 실 도구 위에서 재성립). approver(admin/self)는 interrupt 페이로드로 실려 Approval에 스탬프됨
    → `approvals._may_resolve` 인가에 쓰인다. 도구 실행 실패(서버 다운·프로토콜·타임아웃)는 잡아 graceful
    문자열 + calls_sink status="error"로 — 에이전트 크래시 금지.
    """
    permission = approval["permission"] if approval else None
    approver = (approval.get("approver") or "admin") if approval else "admin"

    async def _execute(kwargs: dict, t0: float) -> str:
        # 실 부수효과: 실제 MCP 서버 도구를 호출한다. 승인됐거나 비위험 도구일 때만 도달.
        try:
            async with asyncio.timeout(_TOOL_TIMEOUT_S):
                raw = await rt.ainvoke(kwargs)
            text = _content_text(raw)
            status = "ok"
        except Exception as exc:
            text = f"도구 실행 실패({server}.{rt.name}): {type(exc).__name__}"
            status = "error"
        calls_sink.append(
            {
                "server": server,
                "tool": rt.name,
                "status": status,
                "ms": int((time.perf_counter() - t0) * 1000) + 1,
                "args": _redact_args(
                    kwargs
                ),  # 스펙 087: 민감 키 마스킹 전 적재(형제 표면 누출 차단)
                # 스펙 211: 직접 MCP 결과도 브로커/RAG와 같은 정화 경로(_sanitize_preview=비밀 마스킹+캡).
                # 사용=공용 전환으로 타인이 크레덴셜 MCP를 배선할 수 있어(사용자 결정: 전부 공용), 결과에
                # 섞인 토큰/비밀이 trace·응답으로 새지 않게 마스킹(codex 211 P2). 구 _cap은 마스킹 없었음.
                "result": _sanitize_preview(text, _RESULT_CAP),
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
                "approver": approver,  # 스펙 177 P2 — Approval에 스탬프돼 _may_resolve 인가에 쓰임
                "server": server,
                "tool": rt.name,
                "action": f"{server}.{rt.name}",
                "args": _redact_args(
                    kwargs
                ),  # 스펙 087: Approval.args(DB 영속)·ApprovalsView로 새기 전 마스킹
                "summary": f"{server}.{rt.name} 실행 — {'본인' if approver == 'self' else '관리자'} 승인 필요",
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


def mcp_connection(server: dict) -> dict | None:
    """서버 dict(`{name,url,transport,auth_token}`)를 `MultiServerMCPClient` 연결 dict로 변환.

    미지원 transport(stdio 등)나 SSRF 차단 URL이면 None(호출부가 그 서버를 스킵). `build_mcp_tools`(그래프
    preload)와 능력 브로커 `McpProvider`(동적 discover→invoke, 스펙 101)가 **이 한 함수를 공유**해
    transport·Bearer·리다이렉트 하드닝(`mcp_http_client_factory`) 정책이 한 곳에서만 산다(드리프트 0).
    호출 전 `net_guard.refresh_allowed_hosts()`는 호출부 책임(루프당 1회 — DB round-trip 중복 방지)."""
    from . import net_guard

    if (server.get("transport") or "").lower() not in ("http", "streamable_http"):
        return None  # stdio 등 미지원 transport
    url = server.get("url") or ""
    try:
        net_guard.guard_url(url)
    except net_guard.SsrfBlockedError:
        return None  # SSRF 차단 서버는 연결 자체를 안 함(부수효과 0)
    headers: dict[str, str] = {}
    token = server.get("auth_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return {
        "transport": "streamable_http",
        "url": url,
        "headers": headers or None,
        # 리다이렉트-SSRF 차단(적대 리뷰 H1): 기본 클라이언트는 3xx를 따라가 가드를 우회하고 토큰을
        # 재전송한다 → follow_redirects=False 팩토리로 fail-closed(a2a_client와 동일 정책).
        "httpx_client_factory": net_guard.mcp_http_client_factory,
    }


def selected_for_server(server: str, selected: list[str] | None) -> set[str] | None:
    """이 서버에 대한 도구 노출 필터(스펙 276) — None=전체 노출(폴백), set=그 런타임명만.

    selected 항목은 런타임명(`server__tool`, _safe_name 산출). 서버명은 NAME_RULE(영소문자·숫자·대시,
    밑줄 금지)이라 `server__` 접두 분리가 모호하지 않다(272 불변식 공유). **이 서버 항목이 하나도
    없으면 None(전체)** — 이 폴백 하나가 세 무회귀를 담당: ①구저장(tools 빈 목록)=기존과 동일,
    ②오버라이드로 서버 통째 추가, ③카탈로그에 도구 목록이 없는 서버의 보존."""
    if not selected:
        return None
    prefix = f"{server}__"
    mine = {s for s in selected if isinstance(s, str) and s.startswith(prefix)}
    return mine or None


async def build_mcp_tools(
    servers: list[dict],
    calls_sink: list[dict],
    tool_policy: dict | None = None,
    selected_tools: list[str] | None = None,
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
        conn = mcp_connection(
            s
        )  # transport 검사·SSRF 가드 공유 헬퍼(브로커와 드리프트 0, 스펙 101)
        if conn is None:
            continue  # 미지원 transport 또는 SSRF 차단 → 그 서버만 스킵
        connections[s["name"]] = conn
        meta[s["name"]] = s

    if not connections:
        return []

    client = MultiServerMCPClient(connections)
    tools: list[StructuredTool] = []
    for name, s in meta.items():
        try:
            raw_tools = await client.get_tools(server_name=name)
        except Exception:
            continue
        enabled = set(s.get("enabled_tools") or [])
        sel = selected_for_server(name, selected_tools)  # 도구 단위 배선 필터(스펙 276)
        for rt in raw_tools:
            if enabled and rt.name not in enabled:
                continue  # enabled_tools 밖 도구는 노출 안 함(서버측 강제)
            if sel is not None and _safe_name(name, rt.name) not in sel:
                continue  # 에이전트가 고른 도구 밖 — 노출 안 함(스펙 276 도구 단위 배선)
            # 스펙 177 단일 리졸버 — 도구 기본(tools_meta) ◁덮음◁ 에이전트 오버라이드(tool_policy).
            appr = resolve_tool_approval(name, rt.name, s.get("tools_meta"), tool_policy)
            tools.append(_wrap_mcp_tool(name, rt, calls_sink, appr))
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
    collections: list[dict], query: str, top_k: int = 4, min_scores: dict | None = None
) -> list[dict]:
    """RAG 검색 공유 코어(스펙 037 본체, 072로 추출). 질의 임베딩 → pgvector cosine → 상위 청크.

    `build_rag_tool`(인-챗 도구, 문자열 포맷)과 `POST /collections/{cid}/search`(시험 엔드포인트, JSON)가
    **같은 코어**를 호출한다 — 평행 구현을 새로 짜면 drift나 "엔드포인트는 초록인데 채팅은 다름"이 된다.

    핵심 불변식: 질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델로** 임베딩해야 같은 벡터 공간에서
    cosine이 의미를 가진다(learning 035 — 진실원을 따른다). `RAG_EMBED_DIMS`로 컬럼 차원은 공유되지만
    모델이 다르면 공간이 달라 검색이 무의미하므로, (base_url, model_id)별로 질의 임베딩을 1회만 호출·캐시.

    `collections`: `_load_context`가 해석한 dict 리스트
    `{id, name, embed_base_url, embed_api_key(복호화됨), embed_model_id}`.
    반환: score(=1-cosine_distance) 내림차순 hit 리스트 `[{"score","filename","text","meta"}]`
    (관련 0건이면 []). meta=엔티티 metadata(스펙 149, 문서형은 None) — 유사도 검색 결과로
    원본 행(각 테이블 id)을 특정하는 축. 실패는 `RagSearchError`로 올린다 — 표현은 호출자가 정한다.
    """
    from sqlalchemy import select  # 지연 임포트(모듈 경량 유지)

    from . import rag_ingest
    from .db import SessionLocal
    from .models import Chunk, Document

    q = (query or "").strip()
    if not q:
        raise RagSearchError("empty", "빈 검색어", "검색어가 비어 있습니다.")
    # 질의 길이 상한(적대 리뷰 103 P2): 엔드포인트는 스키마서 4000자로 막지만 인-챗 도구·브로커 위임
    # 경로는 상한이 없어 거대 질의 1건으로 임베딩 provider를 장시간 점유할 수 있었다. 공유 코어에서
    # 한 번 잘라 세 입구(엔드포인트≤4000이라 무영향·도구·브로커)를 같은 경계로 맞춘다.
    q = q[:4000]
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
    except Exception as exc:
        raise RagSearchError(
            "embed", "임베딩 예외", "문서 검색 실패(질의 임베딩 중 오류)."
        ) from exc

    # 컬렉션별 cosine 검색 → 통합. 각 행: (dist, filename, text, meta, collection). dist 오름차순 = 가까움.
    # collection = 컬렉션명 — 컬렉션별 유사도 임계값(스펙 191 v2) 후필터·인스펙터 표시에 쓴다.
    hits: list[tuple[float, str, str, dict | None, str]] = []
    try:
        async with SessionLocal() as db:
            for c in collections:
                qvec = qvec_cache[(c["embed_base_url"], c["embed_model_id"])]
                dist = Chunk.embedding.cosine_distance(qvec).label("dist")
                rows = (
                    await db.execute(
                        select(Chunk.text, Document.filename, Chunk.meta, dist)
                        .join(Document, Chunk.document_id == Document.id)
                        .where(Chunk.collection_id == c["id"])
                        .order_by(dist)
                        .limit(k)
                    )
                ).all()
                for text, filename, meta, d in rows:
                    hits.append(
                        (float(d), filename or "(파일 미상)", text, meta, c.get("name", ""))
                    )
    except Exception as exc:
        raise RagSearchError("db", "검색 예외", "문서 검색 실패(유사도 검색 중 오류).") from exc

    # 음수 유사도(cosine 거리>1 = 벡터가 반대 방향) 제거: 반-상관 청크는 '근거'가 될 수 없다.
    # 임의 임계값이 아니라 수학적 경계(직교=0)라 정상 매치(양수)는 절대 탈락하지 않는다. 양수
    # 구간의 관련도 임계 튜닝(예 0.3 미만 컷)은 recall 트레이드오프가 있어 빚으로 남긴다(타자검증).
    relevant = [h for h in hits if h[0] <= 1.0 + 1e-9]
    # 컬렉션 간 통합 정렬 후 상위 k. (동일 임베딩 모델 가정 — 다른 모델 간 dist 스케일 차는 빚:
    # 서로 다른 벡터 공간의 거리를 한 리스트로 정렬하면 순위가 의미를 잃는다. 멀티모델 컬렉션
    # 동시 사용은 비권장이며, 강제 방지/스코어 정규화는 후속 스펙으로 남긴다.)
    relevant.sort(key=lambda h: h[0])
    out = [
        {"score": 1.0 - d, "filename": filename, "text": text, "meta": meta, "collection": name}
        for d, filename, text, meta, name in relevant[:k]
    ]
    # 컬렉션별 커트라인을 **표시(annotate)** — 스펙 192. 드롭이 아니라 belowCutoff/cutoff 부착:
    # 인스펙터가 "쓴 문서(used) vs 커트라인 미달로 못 쓴 문서(dropped)"를 구분해 보이게. 에이전트가
    # 실제로 보는 것(used)은 호출자(build_rag_tool·RagProvider)가 `not belowCutoff`로 거른다.
    return _annotate_cutoffs(out, min_scores)


def _norm_score(v) -> float:
    """유사도 임계값 정규화 — 비수치/음수/1 초과는 0(무필터)으로 접는다."""
    try:
        s = float(v)
    except (TypeError, ValueError):
        return 0.0
    return s if 0.0 < s <= 1.0 else 0.0


def _annotate_cutoffs(hits: list[dict], min_scores: dict | None) -> list[dict]:
    """컬렉션별 커트라인 표시(스펙 192) — 각 히트에 `cutoff`(그 컬렉션 임계값)+`belowCutoff`(미달 여부)를
    부착한다. **드롭하지 않는다** — 인스펙터가 used/dropped를 구분해 "못 쓴 문서"까지 보이게. 커트라인이
    없는(0/미설정) 컬렉션의 히트는 키를 안 붙인다(외부 호출자·SearchHit 스키마 안전). 순수 함수.
    used(에이전트가 보는 것)는 호출자가 `[h for h in ... if not h.get("belowCutoff")]`로 거른다."""
    if not isinstance(min_scores, dict) or not min_scores:
        return hits
    norm = {k: _norm_score(v) for k, v in min_scores.items()}
    if not any(norm.values()):
        return hits
    out: list[dict] = []
    for h in hits:
        cut = norm.get(h.get("collection", ""), 0.0)
        if cut > 0:
            h = {**h, "cutoff": round(cut, 3), "belowCutoff": float(h.get("score", 0.0)) < cut}
        out.append(h)
    return out


def used_hits(annotated: list[dict]) -> list[dict]:
    """커트라인 통과분만(스펙 192) — 에이전트가 실제로 보는 문서. belowCutoff=True(미달) 제외.
    build_rag_tool·RagProvider가 format_rag_hits에 넘기기 전에 거른다(에이전트는 미달 문서 안 봄)."""
    return [h for h in annotated if not h.get("belowCutoff")]


def format_rag_hits(results: list[dict]) -> str:
    """검색 hit 리스트 → 사람이 읽을 텍스트 블록(스펙 103 공유 포맷터).

    `build_rag_tool`(인-챗 도구)와 `RagProvider.invoke`(브로커 위임, 스펙 103)가 **같은 포맷**을 쓰도록
    추출한다 — 각자 포맷하면 "도구는 이렇게, 위임은 저렇게" drift(072가 경계한 평행 구현 함정). 관련
    0건도 여기서 문자열로 확정한다(호출자별 재판단 금지).
    """
    if not results:
        return "관련 문서를 찾지 못했습니다."
    lines = [f"[문서 검색 결과 {len(results)}건]"]
    for i, h in enumerate(results, 1):
        snippet = h["text"].strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        row = f"{i}. ({h['filename']}, 유사도 {h['score']:.3f}) {snippet}"
        # 엔티티 hit(스펙 149)은 metadata를 함께 — 에이전트가 원본 행 id를 인용/후속 조회에 쓴다.
        meta = h.get("meta")
        if isinstance(meta, dict) and meta:
            import json as _json

            mtxt = _json.dumps(meta, ensure_ascii=False)
            if len(mtxt) > 300:
                mtxt = mtxt[:300] + "…"
            row += f" [metadata: {mtxt}]"
        lines.append(row)
    return "\n".join(lines)


def _sanitize_preview(text: object, cap: int) -> str:
    """trace 표시용 본문 프리뷰 — 비밀 마스킹 + 캡(스펙 087/092/125). 브로커 resultPreview·직접 result·
    hitsDetail이 **한 경로**로 정화(drift 0). _sanitize가 비밀을 치환한 뒤 cap자로 자른다."""
    from .memory import _sanitize  # 지연 임포트(순환 import 방지, broker와 동일 패턴)

    return _sanitize(text, cap=cap)


def _hits_detail(results: list[dict], cap: int = 240) -> list[dict]:
    """히트별 표시 구조(스펙 191) — 인스펙터가 컬렉션·파일명·유사도·본문 프리뷰를 카드로 그릴 수 있게.
    본문 프리뷰는 **캡(cap자) + 비밀 마스킹**한다(브로커 resultPreview와 동일 규율, 087/092/125 —
    trace에 원문·비밀 누출 0)."""
    out: list[dict] = []
    for h in results:
        # 개행 보존(스펙 255) — 엔티티 직렬화 텍스트("key: value" 라인들)를 인스펙터가 구조화
        # 렌더(EntityFields)하려면 라인 경계가 필요. 평문 청크도 pre-wrap이라 개행 무해.
        snippet = _sanitize_preview(str(h.get("text", "")).strip(), cap)
        item = {
            "score": round(float(h.get("score", 0.0)), 3),
            "filename": h.get("filename", ""),
            "collection": h.get("collection", ""),
            "textPreview": snippet,
        }
        # 엔티티 meta 관통(스펙 255 후속) — 인스펙터=디버그 영역이라 원본 행 데이터를 JSON 뷰어로
        # 제대로 보여준다. JSON 직렬화 2000자 캡(폭주 방지 — 표시-안전 규율의 상한 축), 원문 그대로
        # (스펙 149의 검색 응답과 동일 정밀도 — 마스킹으로 JSON을 깨느니 상한으로 지킨다).
        meta = h.get("meta")
        if isinstance(meta, dict) and meta:
            import json as _json

            if len(_json.dumps(meta, ensure_ascii=False)) <= 2000:
                item["meta"] = meta
        # 스펙 192: 커트라인 표시(used/dropped). belowCutoff/cutoff가 있으면 그대로 전달(인스펙터가
        # "커트라인 미달로 못 쓴 문서"를 회색으로 구분). 커트라인 없는 히트는 키 없음(=used).
        if "belowCutoff" in h:
            item["belowCutoff"] = bool(h["belowCutoff"])
            item["cutoff"] = h.get("cutoff")
        out.append(item)
    return out


def _norm_min_scores(min_scores: dict | None, names: list[str] | None = None) -> dict:
    """컬렉션별 임계값 맵 정규화(스펙 191 v2) — 값 0<x≤1인 항목만 남긴다(0/무효는 무필터라 제외).
    names 주면 그 컬렉션으로 한정(무관 항목 소거)."""
    if not isinstance(min_scores, dict):
        return {}
    allow = set(names) if names is not None else None
    out = {}
    for k, v in min_scores.items():
        if allow is not None and k not in allow:
            continue
        s = _norm_score(v)
        if s > 0:
            out[k] = round(s, 3)
    return out


def build_rag_tool(
    collections: list[dict],
    calls_sink: list[dict],
    min_scores: dict | None = None,
    name: str = "search_documents",
) -> StructuredTool:
    """RAG 문서 검색 도구(스펙 037). `search_collections` 코어를 호출해 결과를 문자열로 포맷한다.

    이 함수는 **얇은 포맷터**다 — 검색 로직은 `search_collections`에 있고(시험 엔드포인트와 공유),
    여기서는 도구 계약(graceful 문자열 + calls_sink 기록)만 책임진다. 실패는 코어가 `RagSearchError`로
    올리고, 도구는 그 `tool_msg`/`record_label`로 매핑해 에이전트를 죽이지 않는다.

    `name`(스펙 268 P1): 노드형은 컬렉션별 도구(`search_documents__<컬렉션>`)로 분리 빌드해 노드가
    컬렉션을 골라 참조한다 — 기본값은 기존 단일 도구 이름(무회귀). calls_sink 기록도 이 이름을 실어
    인스펙터가 어느 컬렉션 검색인지 구분한다.
    """
    names = ", ".join(c["name"] for c in collections)
    # 컬렉션별 임계값 맵 정규화(스펙 191 v2) — 배선된 컬렉션으로 한정, 값 0<x≤1만 유효.
    min_scores = _norm_min_scores(min_scores, [c.get("name", "") for c in collections])

    async def _search(query: str = "", top_k: int = 4) -> str:
        t0 = time.perf_counter()

        def _record(status: str, result: str, n: int = 0, detail: list[dict] | None = None) -> None:
            entry = {
                "server": "rag",
                "tool": name,
                "status": status,
                "ms": int((time.perf_counter() - t0) * 1000) + 1,
                "args": _redact_args({"query": (query or "").strip(), "top_k": top_k}),
                # 스펙 191(codex 적대검토): result도 비밀 마스킹(_sanitize) — 브로커 resultPreview·
                # hitsDetail과 대칭. 직접 경로만 _cap(마스킹 없음)이던 비대칭(문서 본문 내 비밀 노출)을 닫는다.
                "result": _sanitize_preview(result, _RESULT_CAP),
                "hits": n,
                # 스펙 191 v2: 히트별 구조(컬렉션 포함) + 컬렉션별 최소 유사도 맵(인스펙터 카드·기준선용).
                "hitsDetail": detail or [],
                "minScores": dict(min_scores),
            }
            calls_sink.append(entry)

        try:
            results = await search_collections(
                collections, query, top_k, min_scores
            )  # 커트라인 annotate(미드롭)
        except RagSearchError as exc:
            _record("error", exc.record_label)
            return exc.tool_msg

        # 스펙 192: 에이전트가 **실제로 보는 것은 used(커트라인 통과분)** — 미달 문서는 안 넘긴다(필터 의미
        # 유지). trace(hitsDetail)에는 전부 싣는다(used+dropped, 플래그) — 인스펙터가 "못 쓴 문서"를 보이게.
        used = used_hits(results)
        # 결과 본문 스니펫(스펙 131) — "N건 반환" 카운트 대신 실제 구절(_record가 _RESULT_CAP 캡).
        _record(
            "ok",
            format_rag_hits(used) if used else "관련 결과 0건",
            len(used),
            _hits_detail(results),
        )
        return format_rag_hits(used)

    return StructuredTool.from_function(
        coroutine=_search,
        name=name,
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
_MSG_PREVIEW_CAP = (
    160  # messages 델타의 메시지 1건 본문 프리뷰 상한(자) — 채팅 중복이라 짧게(스펙 192 후속)
)
_MSG_PREVIEW_N = 3  # 프리뷰로 펼칠 앞쪽 메시지 수(나머지는 "+N건"으로 카운트만)
_NODE_SUMMARY_CAP = 1200  # 노드 요약 전체 상한(자) — 필드 캡보다 커야 단일 필드가 이중 캡 안 됨
# (codex F3 후속: per-field 캡 후 join이 또 잘려 생략 길이가 거짓이 되던 버그)
_REDACTED = "«redacted»"


# 값 원문을 *노출해도 되는* 알려진 안전 필드(최소 allowlist). 이 기능의 존재이유가 "그 값을 보여주는
# 것"인 필드만. 그 외 임의 키의 문자열 값은 원문 미표시(fail-closed): 키 이름이 평범/비영문이라
# _SENSITIVE_KEY가 못 잡아도 *값 자체* 비밀이 안 샌다(codex 적대 리뷰 F2: 값-비밀 차단). 새 안전 필드
# 추가는 "그 키는 절대 비밀이 아니다"를 보증할 때만.
# 스펙 131 확대: query(analyze가 뽑은 유저 질의)·route(분류 라벨)·delegated(위임 결과 fold, 인스펙터
# brokerCalls resultPreview와 같은 내용) — 출하 그래프(route/plan_execute/orchestrate)의 닫힌 상태 키로
# 전부 비-비밀임을 코드로 확인(131 조사). 미지 키는 여전히 길이만(F2 유지 — 커스텀 플로우 안전).
_VALUE_SAFE_KEYS = frozenset(
    {"plan", "query", "route", "delegated", "delegationNote"}
)  # delegationNote=스펙 289 P3(우리가 생성한 사유 문자열)

# 스펙 087: MCP 호출 인자·결과 redaction(형제 trace 표면). 086 노드델타와 달리 args는 *보여주는 게
# 목적*(인스펙터 디버깅 가치)이라 평범한 키의 값은 보존하고 민감 *키*만 마스킹한다(value-allowlist
# 아닌 key-blocklist — polarity가 정당하게 다름, learning 089 §3 형제 표면판). 시스템 자기 비밀은
# 이 표면에 안 온다(서버 토큰=헤더·모델 키=설정, args 아님) → defense-in-depth.
_ARG_VALUE_CAP = (
    500  # args 문자열 leaf 1개 표시 상한(자) — query·path 등 정상 인자 보존하되 거대값 캡
)
_RESULT_CAP = (
    2000  # 도구 결과 문자열 상한(자) — calls_sink에 무제한 적재(trace 비대) 방어(learning 059)
)
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
    except Exception:
        return "«redact-failed»"


def _cap(s: str, limit: int = _NODE_SUMMARY_CAP) -> str:
    """raw 문자열에서 캡 — 초과분은 정직 표기(no silent truncation). 원문 길이(`len(s)`=O(1))로 표기하되
    복사는 `s[:limit]`만(budgeted) — 거대 문자열을 통째 다시 만들지 않는다(codex F3: post-build cap 금지)."""
    if len(s) <= limit:
        return s
    return s[:limit] + f"…({len(s) - limit}자 생략)"


def _msg_role(m: Any) -> str:
    """메시지(LangChain 객체/dict)의 역할을 사용자 친화 라벨로. 청크형 type명(AIMessageChunk 등)도
    소문자 접두 매칭으로 방어(스펙 086 노트: .type은 청크/비청크 간 불안정)."""
    r = str(
        (m.get("role") or m.get("type") or "")
        if isinstance(m, dict)
        else getattr(m, "type", "") or ""
    )
    low = r.lower()
    for k, v in (("ai", "assistant"), ("human", "user"), ("tool", "tool"), ("system", "system")):
        if low.startswith(k):
            return v
    return r or "msg"


def _summarize_node_update(_node: str, delta: Any) -> str | None:
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
            # messages: 그 단계가 낸 발화를 role+본문 프리뷰로(스펙 192 후속 — plan처럼 execute 등도
            # "무슨 메시지를 냈나"를 타임라인에서 보이게). 채팅 스트림과 일부 중복이라 프리뷰는 짧게 캡.
            # 불변식(086) 유지: 마스킹은 캡 이전에 큰 cap으로(무절단), 잘림은 _cap이 정직 표기. 앞
            # _MSG_PREVIEW_N건만 펼치고 나머지는 카운트(거대 리스트 방어).
            if key == "messages" and isinstance(val, list):
                if not val:
                    parts.append("메시지 0건")
                    continue
                from .memory import _sanitize as _mask

                # 맥락 격리(스펙 260/262) — clean 노드가 낸 RemoveMessage(role=="remove", 상태 삭제
                # 지시)는 내부어라 사람 말로 접는다: "이전 맥락 N개 정리 (격리)". 개수=걷어낸 이전 메시지
                # 수(디버깅 신호 보존). 나머지 실제 발화만 role+본문 프리뷰(앞 N건 + "+N건").
                removes = sum(1 for m in val if _msg_role(m) == "remove")
                rest = [m for m in val if _msg_role(m) != "remove"]
                previews: list[str] = []
                if removes:
                    previews.append(f"이전 맥락 {removes}개 정리 (격리)")
                for m in rest[:_MSG_PREVIEW_N]:
                    raw = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
                    text = _cap(_mask(_content_text(raw), cap=1_000_000), _MSG_PREVIEW_CAP)
                    previews.append(f"{_msg_role(m)}: «{text}»" if text else _msg_role(m))
                extra = max(0, len(rest) - _MSG_PREVIEW_N)
                parts.append(" / ".join(previews) + (f" (+{extra}건)" if extra > 0 else ""))
                continue
            if isinstance(val, str):
                # 안전 키(plan)만 값 원문(budgeted 캡); 그 외 임의 키는 길이만(F2 값-비밀 fail-closed).
                if key in _VALUE_SAFE_KEYS:
                    # 키 접두로 어떤 값인지 명시(131 — 안전 키가 4개로 늘어 구분 필요).
                    # delegated는 위임 결과(untrusted 본문) fold라 **비밀 마스킹 백스톱 필수**
                    # (codex 131 #1 — 캡은 크기 방어일 뿐). 마스킹은 캡 **이전에**(cap 크게 줘 무절단),
                    # 잘림은 기존 _cap이 담당 — "…N자 생략" 정직 표기 보존(086 U2 불변식).
                    from .memory import _sanitize as _mask

                    parts.append(f"{key}: {_cap(_mask(val, cap=1_000_000), _FIELD_CAP)}")
                else:
                    parts.append(f"{key}: <{len(val)}자>")
            elif isinstance(val, (list, tuple)):
                parts.append(f"{key}[{len(val)}]")
            elif isinstance(val, dict):
                # 중첩 dict도 키만(중첩 안의 비밀 누출 차단 — 값 펼치지 않음). 키 목록도 캡(거대 dict 방어).
                inner = _cap(
                    ", ".join(_REDACTED if _SENSITIVE_KEY.search(str(k)) else str(k) for k in val),
                    80,
                )
                parts.append(f"{key}{{{inner}}}")
            elif val is None or isinstance(val, (bool, int, float)):
                parts.append(f"{key}={val}")  # 스칼라(유한 길이, 비밀 위험 낮음)
            else:
                parts.append(f"{key}=<{type(val).__name__}>")  # 미지 타입은 타입명만(fail-closed)
        text = _cap(" · ".join(p for p in parts if p))
        return text or None
    except Exception:
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
