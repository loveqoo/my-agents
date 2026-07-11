"""도구 접근 하이브리드 (스펙 203) — 도구가 임계를 넘으면 전체 바인딩 대신 검색 창구로.

직접 바인딩은 도구 수에 비례해 프롬프트가 커진다. 임계 초과 시 주입된 도구 목록을 **메타 도구
2개**(search_tools·call_tool)로 대체해, 모델이 필요한 도구를 검색→호출한다(컨텍스트 크기 일정).

- 에이전트 종류 불변: 디스커버는 부품, 조율형(위임·fold·신뢰경계)은 형태 — 여긴 부품만 빌린다.
- **브로커 미경유**: 브로커는 per-user RBAC(capabilities 축)라 직접형의 권한 의미(에이전트 배선=사용)
  를 바꾼다. 메타 도구는 이미 주입된(HIL/트레이스 래핑된) 도구 목록 *위* 래퍼 — 권한·래핑 그대로 통과.
"""

from __future__ import annotations

import json
import os

from langchain_core.tools import tool

# 임계(기본 10) — 이하면 직접 바인딩(무회귀), 초과면 검색 창구. FE 미러: AgentForm 도구 안내 문구.
DISCOVER_THRESHOLD = int(os.environ.get("TOOLS_DISCOVER_THRESHOLD", "10"))

# discovery 모드에서 시스템 프롬프트에 덧붙일 사용 안내(직접형·플랜형 공용).
DISCOVERY_HINT = (
    "연결된 도구가 많아 검색 방식으로 제공됩니다 — 먼저 search_tools(query=검색어)로 알맞은 도구를 "
    "찾고, call_tool(name=도구이름, arguments=인자 JSON 문자열)로 호출하세요. "
    "도구가 필요 없는 질문이면 그냥 답하세요."
)


def _first_line(text: str | None, cap: int = 160) -> str:
    return ((text or "").strip().splitlines() or [""])[0][:cap]


def _rank(tools: list, query: str) -> list:
    """어휘 랭킹(브로커 rank_candidates와 동사상) — 이름 매치 가중 2·설명 매치 1. 필터가 아니라
    랭킹(스펙 124 교훈: 하드필터는 자연어 쿼리서 전멸) — 무매치여도 상위 후보는 돌려준다."""
    terms = [w for w in query.lower().split() if w]
    scored = []
    for candidate in tools:  # 랭킹 후보(langchain `tool` 데코레이터와 이름 충돌 회피)
        name = (candidate.name or "").lower()
        desc = (candidate.description or "").lower()
        score = sum((2 if w in name else 0) + (1 if w in desc else 0) for w in terms)
        scored.append((score, candidate))
    scored.sort(key=lambda x: -x[0])
    return [t for _s, t in scored]


def _meta_tools(tools: list) -> list:
    """주입 도구 목록 위의 검색 창구 — search_tools(어휘 랭킹)·call_tool(이름 디스패치)."""
    by_name = {t.name: t for t in tools}

    @tool
    def search_tools(query: str, limit: int = 5) -> str:
        """사용 가능한 도구를 검색한다 — 이름·설명·인자 요약 JSON. 어떤 도구가 있는지 모를 때 먼저
        호출하고, 찾은 이름으로 call_tool을 호출한다."""
        limit = max(1, min(int(limit), 10))
        hits = _rank(tools, query)[:limit]
        return json.dumps(
            {
                "query": query,
                "total": len(tools),
                "results": [
                    {
                        "name": t.name,
                        "description": _first_line(t.description),
                        "args": {k: (v.get("type") or "string") for k, v in (t.args or {}).items()},
                    }
                    for t in hits
                ],
            },
            ensure_ascii=False,
        )

    @tool
    async def call_tool(name: str, arguments: str = "{}") -> str:
        """search_tools로 찾은 도구를 이름으로 호출한다. arguments는 그 도구의 인자 JSON 객체 문자열
        (예: '{"query": "장영실"}').

        주의: 인자명을 `args`로 하면 LangChain 예약어와 충돌해 스키마가 `v__args`로 둔갑 —
        모델이 스키마대로 호출하면 실제 함수와 어긋나 실패한다(스펙 203 live서 실측). `arguments` 고정."""
        t = by_name.get(name)
        if t is None:
            near = [x.name for x in _rank(tools, name)[:3]]
            return json.dumps(
                {"error": f"도구 '{name}' 없음", "candidates": near}, ensure_ascii=False
            )
        try:
            parsed = json.loads(arguments or "{}")
            if not isinstance(parsed, dict):
                return json.dumps({"error": "arguments는 JSON 객체여야 합니다"}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {"error": f"arguments JSON 파싱 실패: {str(exc)[:120]}"}, ensure_ascii=False
            )
        try:
            # 래핑된 원 도구를 그대로 호출 — HIL interrupt·트레이스가 이 안에서 그대로 발화한다.
            result = await t.ainvoke(parsed)
        except Exception as exc:
            return json.dumps({"error": f"도구 실행 실패: {str(exc)[:200]}"}, ensure_ascii=False)
        return (
            result
            if isinstance(result, str)
            else json.dumps(result, ensure_ascii=False, default=str)
        )

    return [search_tools, call_tool]


def effective_tools(tools: list | None) -> tuple[list, bool]:
    """하이브리드 게이트 — (실제 바인딩할 도구, discovery 모드 여부).
    임계 이하: 그대로(코드 경로 동일 = 무회귀). 초과: 메타 도구 2개."""
    ts = list(tools or [])
    if len(ts) <= DISCOVER_THRESHOLD:
        return ts, False
    return _meta_tools(ts), True
