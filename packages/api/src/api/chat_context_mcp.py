"""MCP 서버 실행 배선 해석 — chat_context.py에서 분할(스펙 394 P5).

_resolve_mcp_servers(구 CC 18, 최위험)는 서버별 projection(_mcp_server_projection)과 tool filter
정책(_resolve_tool_filter)으로 분해(codex 자문). **projection dict의 필드명/값 의미는 동결** —
그래프 캐시 지문(스펙 371, _graph_fingerprint)과 runtime.build_mcp_tools가 소비.
파사드는 chat_context.py(재수출 계약).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto
from .models import McpServer
from .references import config_names


def _pinned_content(pinned: dict) -> tuple[str, str, list, dict]:
    """pin payload의 저작 콘텐츠(url·transport·enabled_tools·tools_meta) — 스펙 370 오버레이."""
    return (
        pinned.get("url") or pinned.get("endpoint") or "",
        pinned.get("transport") or "http",
        list(pinned.get("enabled_tools") or []),
        pinned.get("tools_meta") or {},
    )


def _head_content(row: McpServer) -> tuple[str, str, list, dict]:
    """head(라이브 행)의 저작 콘텐츠 — pin 없을 때(369 경계)."""
    return (
        row.url or row.endpoint or "",
        row.transport or "http",
        list(row.enabled_tools or []),
        row.tools_meta or {},
    )


def _projection_content(row: McpServer, pinned: dict | None) -> tuple[str, str, list, dict]:
    """저작 콘텐츠 선택 — pin이 있으면 못박은 버전 payload, 없으면 head 라이브(369 경계)."""
    return _pinned_content(pinned) if pinned is not None else _head_content(row)


async def _mcp_server_projection(db: AsyncSession, row: McpServer, pins: dict | None) -> dict:
    """서버 행 → runtime.build_mcp_tools가 붙는 dict 하나(스펙 054).

    auth_token은 저장된 Fernet 암호문을 복호화한 평문(provider.api_key 동형) — 마스킹/빈값이면
    None이라 헤더 생략(a2a_client 규칙). 비밀(auth)·운영(published/status)은 항상 head 라이브.
    유효 버전(스펙 371 D1 캐시 키)은 pin 우선, 없으면 head 현재 버전 — 369 불변성 덕에
    (name, version)이 콘텐츠를 유일하게 가리킨다(무효화 로직 불요)."""
    from .block_versions import resolve_pinned

    token = None if crypto.is_masked(row.auth) else crypto.decrypt(row.auth)
    pinned = await resolve_pinned(db, pins, "mcp-server", row.name)
    url, transport, enabled, tools_meta = _projection_content(row, pinned)
    return {
        "name": row.name,
        "version": (pins or {}).get(f"mcp-server:{row.name}") or row.version,
        "url": url,
        "transport": transport,
        "enabled_tools": enabled,
        "auth_token": token,
        "tools_meta": tools_meta,  # 도구 승인 정책 리졸버용(스펙 177)
    }


def _resolve_tool_filter(cfg: dict) -> list:
    """tool_names(스펙 276) — tools(런타임명 목록)는 서버 풀 위의 노출 필터. **직접형(DefaultUiAgent)
    전용**: 노드형(pipeline)은 노드가 자기 tools로 풀을 필터하므로 에이전트-레벨 tools로 풀을 좁히면
    노드 도구가 조용히 미바인딩된다(codex 276 Low). 조율형은 capabilities가 도구를 관장. 그래서 이
    둘은 필터 미적용(풀=전체) — UI finalize의 "pipeline/조율형은 tools:[] 저장" 규칙을 백엔드에서도
    강제(의도 값 게이트, 클라이언트 신뢰 안 함)."""
    if cfg.get("impl") in ("pipeline", "orchestrate", "orchestrate_ranked"):
        return []
    return config_names(cfg, "tools")


async def _resolve_mcp_servers(
    db: AsyncSession, cfg: dict, pins: dict | None = None
) -> tuple[list[dict], list]:
    """등록된 MCP 서버를 runtime.build_mcp_tools가 붙을 수 있는 dict로 해석(스펙 054).

    enabled_tools가 비면 서버 전체 도구 노출(get_tools가 결정). 사용=공용(스펙 211, RAG 172 동형)
    — 등록된 MCP는 어떤 에이전트든 배선 가능(구 113 배선 인가 제거). auth 토큰 있는 MCP도 공용
    배선(공유 카탈로그 모델), 관리(수정/삭제)는 여전히 소유자만. 반환 (mcp_servers, tool_names)."""
    mcp_servers: list[dict] = []
    mcps = config_names(cfg, "mcps")  # 삭제 가드와 동일 normalizer(drift 0, codex P2)
    if mcps:
        rows = (await db.execute(select(McpServer).where(McpServer.name.in_(mcps)))).scalars().all()
        for row in rows:
            mcp_servers.append(await _mcp_server_projection(db, row, pins))
    return mcp_servers, _resolve_tool_filter(cfg)
