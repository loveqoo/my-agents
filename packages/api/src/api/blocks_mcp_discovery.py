"""MCP 라이브 탐색·도구 메타 파싱 — blocks.py에서 분할(스펙 393 P1).

_tool_info(구 CC 15)는 순수함수 3개(required 추출·타입 라벨·파라미터 요약)로 분해(codex 자문).
캡 상수는 mcp_tool_meta 단일 출처 유지. 파사드는 blocks.py(재수출 계약).
"""

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from .mcp_tool_meta import (
    PARAM_NAME_CAP,
    PARAM_TYPE_CAP,
    TOOL_DESC_CAP,
    TOOL_NAME_CAP,
    TOOL_PARAMS_CAP,
    TOOLS_META_CAP,
)
from .schemas import McpDiscoverResult

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def _tool_required_names(t: "BaseTool") -> set[str]:
    """도구 스키마의 required 파라미터 이름 집합 — 파생 실패는 빈 집합(표시용 fail-safe)."""
    try:
        schema = t.tool_call_schema
        js = schema.model_json_schema() if hasattr(schema, "model_json_schema") else (schema or {})
        return set(js.get("required") or [])
    except Exception:
        return set()


def _param_type_label(ps: object) -> str:
    """파라미터 스키마 조각 → 표시용 타입 문자열("any" 폴백, anyOf는 슬래시 결합)."""
    if isinstance(ps, dict):
        if isinstance(ps.get("type"), str):
            return ps["type"]
        if isinstance(ps.get("anyOf"), list):
            joined = "/".join(str(x.get("type", "?")) for x in ps["anyOf"] if isinstance(x, dict))
            return joined or "any"
    return "any"


def _tool_param_summaries(t: "BaseTool") -> list[dict]:
    """도구 args → [{name,type,required}] (캡 적용). 파생 실패는 [](탐색 자체를 죽이지 않는다)."""
    try:
        props = dict(getattr(t, "args", None) or {})
        required = _tool_required_names(t)
        return [
            {
                "name": str(pname)[:PARAM_NAME_CAP],
                "type": _param_type_label(ps)[:PARAM_TYPE_CAP],
                "required": pname in required,
            }
            for pname, ps in list(props.items())[:TOOL_PARAMS_CAP]
        ]
    except Exception:
        return []


def _tool_info(t: "BaseTool") -> dict:
    """langchain 도구 객체 → {name, description, params[{name,type,required}]} (스펙 151). 순수 함수."""
    return {
        "name": str(getattr(t, "name", ""))[:TOOL_NAME_CAP],
        "description": str(getattr(t, "description", "") or "")[:TOOL_DESC_CAP],
        "params": _tool_param_summaries(t),
    }


def _tools_meta_from_details(details: list[dict], prior: dict | None = None) -> dict:
    """toolsDetail 리스트 → 저장용 dict(name→{description, params[, approval]}). 서버당 상한 적용.

    approval(도구 승인 정책, 스펙 177)은 **라이브 탐색이 보고하지 않는 관리자 데이터**다. 재탐색 시
    이 함수가 tools_meta를 통째 교체하므로, `prior`(기존 tools_meta)에서 도구별 approval을 **이월
    보존**하지 않으면 재탐색 한 번에 관리자가 켠 승인 게이트가 소멸한다(적대 검토 P0 — 단위는 초록,
    reconcile 왕복만 잡는 결함). 도구명이 재탐색으로 사라지면 그 approval도 함께 사라진다(정상)."""
    prior = prior or {}
    out: dict = {}
    for detail in details[:TOOLS_META_CAP]:
        name = detail.get("name")
        if not name:
            continue
        entry = {"description": detail.get("description", ""), "params": detail.get("params", [])}
        prev = prior.get(name)
        pa = prev.get("approval") if isinstance(prev, dict) else None
        if isinstance(pa, dict) and pa.get("required"):
            entry["approval"] = {"required": True}  # 관리자 정책 이월(탐색 결과엔 없음)
        out[name] = entry
    return out


async def _live_discover(url: str, token: str | None) -> McpDiscoverResult:
    """MCP 라이브 탐색 공유 코어(스펙 054 E·151) — SSRF guard → 연결 → 이름+메타.
    discover(폼, 평문/마스킹 토큰)와 rediscover(저장 서버, 복호 토큰)가 공유(드리프트 0).
    SsrfBlockedError는 HTTPException 400으로 올린다(보안 경계 ≠ 정상 연결실패)."""
    import asyncio
    import time

    from langchain_mcp_adapters.client import MultiServerMCPClient

    from . import net_guard

    try:
        await net_guard.refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064)
        net_guard.guard_url(url)
    except net_guard.SsrfBlockedError as exc:
        # 보안 경계 위반은 4xx(정상 연결실패의 ok=False와 구분) — 스펙 054 완료조건 ④.
        raise HTTPException(status_code=400, detail=str(exc)) from None

    headers = {"Authorization": f"Bearer {token}"} if token else None
    t0 = time.perf_counter()
    try:
        client = MultiServerMCPClient(
            {
                "probe": {
                    "transport": "streamable_http",
                    "url": url,
                    "headers": headers,
                    # 리다이렉트-SSRF 차단(적대 리뷰 H1) — runtime.build_mcp_tools와 동일 정책.
                    "httpx_client_factory": net_guard.mcp_http_client_factory,
                }
            }
        )
        async with asyncio.timeout(15):
            tools = await client.get_tools(server_name="probe")
    except Exception:
        ms = int((time.perf_counter() - t0) * 1000)
        return McpDiscoverResult(ok=False, reachable=False, latencyMs=ms, detail="연결 실패")
    ms = int((time.perf_counter() - t0) * 1000)
    names = [t.name for t in tools]
    # 메타(설명·파라미터, 스펙 151) — dict를 pydantic이 McpToolInfo로 검증·강제(모델 생성 시).
    details: list[Any] = [_tool_info(t) for t in tools[:TOOLS_META_CAP]]
    return McpDiscoverResult(
        ok=True,
        reachable=True,
        tools=names,
        toolsDetail=details,
        latencyMs=ms,
        detail=f"{len(names)}개 도구 발견",
    )
