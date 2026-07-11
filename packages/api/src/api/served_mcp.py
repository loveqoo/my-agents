"""내부(커스텀) MCP를 외부로 서빙 (스펙 156, 실사용 #4).

우리는 외부 MCP를 **등록해 클라이언트로 붙어 쓴다**(runtime.build_mcp_tools + MultiServerMCPClient).
이 파일은 그 반대편 — 우리가 코드로 정의한 도구를 **진짜 MCP 엔드포인트로 서빙**해 외부 MCP
클라이언트/에이전트가 붙게 한다. "langgraph에서 mcp 만들어 외부 공개"의 실체:
LangChain 도구(@tool) → `to_fastmcp` → `FastMCP(..., tools=[...])` → streamable-HTTP(mock_mcp 동형).

에이전트 모델 미러: 에이전트는 A2A로 서빙(154), MCP는 여기서 서빙. external MCP는 **서빙 불가**
(재공개 봉인, 스펙 152) — 서빙 대상은 우리가 호스팅하는 source="custom" MCP뿐이며, 그중에서도
이 레지스트리에 실 정의가 있는 이름만 서빙된다(등록 행만 있고 정의 없는 이름은 서빙 안 됨).

게이트는 main.py의 마운트 가드가 요청마다 DB로 확인한다(published + source=custom + 레지스트리 존재).
정의만 있고 미공개면 404(노출 안 된 것 누출 금지, a2a_server 동형).
"""

from langchain_core.tools import tool
from langchain_mcp_adapters.tools import to_fastmcp
from mcp.server.fastmcp import FastMCP

# 서빙 대상 유래(스펙 156) — 우리가 코드로 정의·호스팅하는 MCP만. external은 봉인(152), local은
# 외부/self-host 등록분이라 서빙 대상 아님(우리 정의가 아님).
SERVABLE_SOURCE = "custom"

# 서빙 경로 프리픽스(mock_remote/_remote 관례) — main.py 마운트와 단일 소스.
SERVED_MCP_PREFIX = "/_served/mcp"


# ---- 커스텀 도구(LangChain @tool → to_fastmcp) ----
@tool
def add(a: int, b: int) -> int:
    """두 정수를 더한다(결정적)."""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """두 정수를 곱한다(결정적)."""
    return a * b


@tool
def echo(text: str) -> str:
    """입력 텍스트를 그대로 돌려준다(연결·왕복 확인용)."""
    return text


# ---- 타겟팅 카탈로그(스펙 188 데모 — read-only·결정적, 무인증 서빙 안전 불변식 충족) ----
# 산출물형 targeting 데모가 소비: list_entities(요소 매칭용 동의어) → get_entity(값 후보).
_TARGETING_ENTITIES: list[dict] = [
    {
        "id": "purchase_history",
        "label": "구매이력",
        "synonyms": ["구매 이력", "구매이력", "구매", "산 적"],
        "candidates": ["최근", "7일 전", "최근 한 달"],
    },
    {
        "id": "age_band",
        "label": "나이",
        "synonyms": ["나이", "연령", "20대", "30대", "40대", "50대"],
        "candidates": ["20대", "30대", "40대", "50대"],
    },
    {
        "id": "region",
        "label": "거주지(시)",
        "synonyms": ["거주", "사는", "지역", "서울", "부산", "대구", "인천", "광주"],
        "candidates": ["서울", "부산", "대구", "인천", "광주"],
    },
    {
        "id": "gender",
        "label": "성별",
        "synonyms": ["성별", "남성", "여성", "남자", "여자"],
        "candidates": ["남성", "여성"],
    },
]


@tool
def list_entities() -> str:
    """타겟팅 엔티티 카탈로그 목록(id·label·synonyms) — JSON."""
    import json

    return json.dumps(
        {"entities": [{k: e[k] for k in ("id", "label", "synonyms")} for e in _TARGETING_ENTITIES]},
        ensure_ascii=False,
    )


@tool
def get_entity(entity_id: str) -> str:
    """타겟팅 엔티티의 성격 조회 — 값 후보(candidates) 포함 JSON."""
    import json

    e = next((x for x in _TARGETING_ENTITIES if x["id"] == entity_id), None)
    return json.dumps(e or {"error": "not found"}, ensure_ascii=False)


# ---- web-fetch(스펙 201) — "사이트 주소를 조립해 패치"(사용자 설계). 위키피디아 공식 API,
# 호스트 고정(사용자 입력은 검색어·제목뿐 → SSRF 0), read-only. ----
_WIKI_LANGS = {"ko", "en"}  # lang이 곧 호스트 — allowlist로 임의 호스트 조립 차단
_FETCH_TIMEOUT = 8.0
_FETCH_MAX_BYTES = 512 * 1024  # 응답 raw 바이트 캡(cap-the-raw-source)
_FETCH_UA = "my-agents/1.0 (web-fetch custom MCP)"  # 위키 API가 UA 명시를 요구


def _wiki_get(url: str, params: dict | None = None) -> dict:
    """위키 API GET 공통 — 타임아웃·raw 바이트 캡·리다이렉트 후 호스트 재검증·JSON 파싱.
    실패는 raise 대신 {'error': …}(도구는 graceful — 에이전트가 실패를 읽고 진행)."""
    import httpx

    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT, headers={"User-Agent": _FETCH_UA}, follow_redirects=True
        ) as c:
            r = c.get(url, params=params)
        # 리다이렉트가 위키 밖으로 새면 차단 — 가드는 부수효과 발생 지점에서(installed≠covering).
        host = r.url.host or ""
        if not (host == "wikipedia.org" or host.endswith(".wikipedia.org")):
            return {"error": f"비허용 호스트로 리다이렉트됨({host})"}
        if len(r.content) > _FETCH_MAX_BYTES:
            return {"error": f"응답이 너무 큽니다({len(r.content)}B > {_FETCH_MAX_BYTES}B)"}
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        return r.json()
    except Exception as exc:
        return {"error": str(exc)[:200]}


@tool
def wiki_search(query: str, limit: int = 5, lang: str = "ko") -> str:
    """위키피디아(백과사전)에서 문서를 검색한다 — 제목·요약 스니펫 목록(JSON).

    이럴 때 사용: 사용자가 "위키(피디아)에서/백과사전에서 찾아줘·검색해줘"라고 하거나, 인물·사건·
    개념·지명 등 사실 정보가 필요한 질문일 때. 문서 제목을 정확히 모르면 이 도구를 먼저 호출해
    제목을 찾은 뒤 wiki_page로 본문을 읽는다. lang: ko|en."""
    import json
    import re

    if lang not in _WIKI_LANGS:
        return json.dumps(
            {"error": f"lang은 {sorted(_WIKI_LANGS)}만 지원합니다"}, ensure_ascii=False
        )
    limit = max(1, min(int(limit), 10))  # 1~10 클램프
    data = _wiki_get(
        f"https://{lang}.wikipedia.org/w/api.php",
        {
            "action": "query",
            "list": "search",
            "srsearch": query[:300],
            "format": "json",
            "srlimit": limit,
            "utf8": 1,
        },
    )
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)
    hits = [
        {"title": h.get("title", ""), "snippet": re.sub(r"<[^>]+>", "", h.get("snippet", ""))[:300]}
        for h in (data.get("query", {}).get("search", []) or [])
    ]
    return json.dumps({"query": query, "lang": lang, "results": hits}, ensure_ascii=False)


@tool
def wiki_page(title: str, lang: str = "ko") -> str:
    """위키피디아 문서 하나의 요약 본문을 가져온다(JSON: title·extract·url).

    이럴 때 사용: 읽을 문서의 제목을 알 때(사용자가 제목을 말했거나 wiki_search 결과에서 골랐을 때)
    그 내용을 실제로 읽어 답에 인용한다. 제목이 불확실하면 wiki_search 먼저. lang: ko|en."""
    import json
    from urllib.parse import quote

    if lang not in _WIKI_LANGS:
        return json.dumps(
            {"error": f"lang은 {sorted(_WIKI_LANGS)}만 지원합니다"}, ensure_ascii=False
        )
    data = _wiki_get(
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title[:200], safe='')}"
    )
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(
        {
            "title": data.get("title", title),
            "extract": (data.get("extract") or "")[:2000],
            "url": ((data.get("content_urls") or {}).get("desktop") or {}).get("page", ""),
        },
        ensure_ascii=False,
    )


# 서빙 MCP 정의(단일 출처) — 이름 → (도구 리스트, 메타). 시드 카탈로그·서빙 앱이 이걸 공유(드리프트 0).
_DEFS: dict[str, list] = {
    "calc-tools": [add, multiply, echo],
    "targeting-catalog": [list_entities, get_entity],
    "web-fetch": [wiki_search, wiki_page],  # 스펙 201 — 위키 주소 조립→패치(read-only)
}

# 시드 카탈로그가 쓰는 도구 이름/메타(mock_mcp 패턴 — 평행 리터럴 드리프트 방지).
SERVED_MCP_TOOLS: dict[str, list[str]] = {
    name: [t.name for t in tools] for name, tools in _DEFS.items()
}
SERVED_MCP_TOOLS_META: dict[str, dict] = {
    name: {
        t.name: {
            "description": (t.description or "").strip(),
            # t.args = {argname: {title,type,...}} — 서빙 도구가 요구하는 인자는 전부 필수(간단 도구).
            "params": [
                {"name": pn, "type": (pinfo.get("type") or "string"), "required": True}
                for pn, pinfo in (t.args or {}).items()
            ],
        }
        for t in tools
    }
    for name, tools in _DEFS.items()
}


def _build(name: str, tools: list) -> FastMCP:
    """LangChain 도구를 FastMCP로 서빙 가능한 앱으로 — to_fastmcp 변환 후 constructor tools=로 등록.
    stateless_http=True: 매 요청 독립(영속 세션 매니저 불필요, mock_mcp 동형)."""
    fastmcp_tools = [to_fastmcp(t) for t in tools]
    return FastMCP(name, streamable_http_path="/", stateless_http=True, tools=fastmcp_tools)


# 안전 불변식(스펙 156, codex Low 경계): 서빙 라우트는 전역 인증 밖(mock_mcp처럼) — published custom
# MCP는 **무인증 공개 API**다. 그래서 서빙 도구는 반드시 **부수효과 없는(read-only/순수) 도구**여야
# 한다(HIL 승인 대상 delete_record류를 서빙하면 무인증 실행면이 된다). 새 도구를 서빙에 추가하려면
# 이 allowlist에 명시적으로 등록해야 부팅이 통과 — "무심코 위험 도구 서빙"을 부팅에서 강제 차단한다.
_SIDE_EFFECT_FREE_TOOLS = {
    "add",
    "multiply",
    "echo",
    "list_entities",
    "get_entity",  # 고정 dict 조회(스펙 188)
    "wiki_search",
    "wiki_page",  # 위키 read-only 조회(스펙 201) — 고정 호스트·바이트 캡·타임아웃
}
for _n, _ts in _DEFS.items():
    _unsafe = {t.name for t in _ts} - _SIDE_EFFECT_FREE_TOOLS
    if _unsafe:
        raise RuntimeError(
            f"서빙 MCP '{_n}'에 부수효과 미검증 도구 {sorted(_unsafe)} — 무인증 서빙 대상은 "
            "_SIDE_EFFECT_FREE_TOOLS에 명시적으로 등록된 순수 도구만 허용됩니다(스펙 156 안전 불변식)."
        )

# 이름 → FastMCP 서버(부팅 시 1회 구성). main.py가 각 이름을 `/_served/mcp/{name}`에 가드와 함께 마운트.
SERVED_MCPS: dict[str, FastMCP] = {name: _build(name, tools) for name, tools in _DEFS.items()}


def served_url(name: str, base: str = "http://127.0.0.1:8000") -> str:
    """서빙 URL(끝 슬래시 필수 — mount+path 조합이 trailing-slash 기대, mock_mcp 동형)."""
    return f"{base.rstrip('/')}{SERVED_MCP_PREFIX}/{name}/"


async def _is_served(name: str) -> bool:
    """서빙 게이트(스펙 156) — DB로 요청마다 확인. published + source=custom + 레지스트리 존재.
    미공개/미등록/유래 불일치면 False → 404(노출 안 된 것의 존재·구성 누출 금지, a2a_server 동형).
    external은 애초에 여기 못 옴(source=custom만 통과) — 재공개 봉인(152) 이중 게이트."""
    from sqlalchemy import select

    from .db import SessionLocal
    from .models import McpServer

    if name not in SERVED_MCPS:
        return False
    async with SessionLocal() as db:
        row = (
            await db.execute(select(McpServer).where(McpServer.name == name))
        ).scalar_one_or_none()
    return row is not None and row.source == SERVABLE_SOURCE and bool(row.published)


def guarded_app(name: str, inner):
    """`inner`(FastMCP streamable_http_app)를 공개 게이트로 감싼 ASGI 앱. http 요청만 게이트하고
    lifespan 등은 통과(세션 매니저는 main lifespan이 직접 run — 마운트 lifespan 자동실행 안 됨)."""

    async def app(scope, receive, send):
        if scope.get("type") != "http":
            await inner(scope, receive, send)
            return
        if not await _is_served(name):
            await send(
                {
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":"served mcp not found"}',
                }
            )
            return
        await inner(scope, receive, send)

    return app
