"""MCP 서버 응답 직렬화(presenter) — blocks.py에서 분할(스펙 393 P1, 순수 이동).

auth 마스킹·서빙 URL·감사 JSON·ORM→DTO 변환. 파사드는 blocks.py(재수출 계약).
"""

from . import crypto
from .models import McpServer
from .schemas import McpServerOut
from .serializers import _iso, audit_of


def _mcp_auth_masked(obj: McpServer) -> str | None:
    """저장된 auth(암호문)를 응답용 마스킹값으로 — 평문/암호문 절대 미노출(스펙 054 F, 누출-안전)."""
    return crypto.SECRET_MASK if obj.auth else None


def _mcp_served_url(obj: McpServer) -> str | None:
    """서빙 URL(스펙 156) — source=custom이고 레지스트리에 실 정의가 있는 이름만. 그 외 None
    (등록만 있고 서빙 정의 없는 custom 이름은 URL을 광고하지 않는다). base는 A2A_SELF_BASE_URL 재사용."""
    from . import served_mcp

    if obj.source != served_mcp.SERVABLE_SOURCE or obj.name not in served_mcp.SERVED_MCPS:
        return None
    import os

    base = (os.environ.get("A2A_SELF_BASE_URL") or "http://127.0.0.1:8000").strip()
    return served_mcp.served_url(obj.name, base)


def _audit_json(row: object) -> dict:
    """감사 4값을 JSON 직렬화 가능한 형태로(블록 목록은 dict를 직접 조립한다 — 스펙 344).
    datetime은 ISO 문자열로, actor는 **문자열 그대로**(user 테이블 resolve 금지 — 스펙 343 전제)."""
    return {
        "created_at": _iso(getattr(row, "created_at", None)),
        "updated_at": _iso(getattr(row, "updated_at", None)),
        "created_by": getattr(row, "created_by", None),
        "updated_by": getattr(row, "updated_by", None),
    }


def mcp_to_out(obj: McpServer) -> McpServerOut:
    """ORM → 응답 DTO. auth는 마스킹해 평문 토큰을 절대 흘리지 않는다."""
    return McpServerOut(
        served_url=_mcp_served_url(obj),
        id=obj.id,
        name=obj.name,
        description=obj.description,  # 설명(스펙 210)
        source=obj.source,
        transport=obj.transport,
        url=obj.url,
        endpoint=obj.endpoint,
        tools=list(obj.tools or []),
        enabled_tools=list(obj.enabled_tools or []),
        tools_meta=obj.tools_meta,  # 도구 메타(스펙 151)
        status=obj.status,
        published=obj.published,
        auth=_mcp_auth_masked(obj),
        owner_id=obj.owner_id,  # 스펙 112(can_manage는 list서 세팅)
        version=obj.version,  # 스펙 369
        **audit_of(obj),  # 감사 4값(스펙 344)
    )
