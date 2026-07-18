"""관리자 UI 블록 집계(`GET /blocks`) — blocks.py에서 분할(스펙 393 P5, 순수 이동).

REST DTO와 **다른** 관리자 UI 계약(camelCase enabledTools·toolsMeta·usedBy·chunkSize… —
BlocksView.tsx가 그대로 소비)이라 항목 조립은 바이트 동일 이동(필드 변경 금지). 파사드는 blocks.py.
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .auth import current_principal
from .blocks_presenters import _audit_json, _mcp_auth_masked, _mcp_served_url
from .db import get_session
from .models import Agent, Collection, McpServer, MemoryType, Prompt, User
from .ownership import may_manage
from .references import _config_has
from .serializers import _iso

router = APIRouter(tags=["blocks"])

_CATEGORY_META: dict[str, dict[str, str]] = {
    "prompt": {
        "label": "프롬프트",
        "icon": "smile",
        "color": "var(--magenta-6)",
        "desc": "에이전트가 따르는 성격·말투 정의(재사용 가능).",
    },
    "memory": {
        "label": "메모리 타입",
        "icon": "bulb",
        "color": "var(--purple-6)",
        "desc": (
            "에이전트가 컨텍스트를 저장·검색하는 메모리 타입. 서로 배타적이지 않으며, "
            "에이전트마다 여러 타입을 동시에 켤 수 있습니다."
        ),
    },
    "embedding": {
        "label": "RAG 컬렉션",
        "icon": "appstore",
        "color": "var(--cyan-7)",
        "desc": (
            "임베딩 모델 1개로 묶인 문서 컬렉션(RAG). 문서를 업로드하면 청킹·임베딩되어 "
            "pgvector에 적재되고, 에이전트가 의미 검색으로 참조합니다. 차원은 임베딩 모델에 "
            "맞춰 생성 시 고정됩니다. 에이전트마다 0개 이상 연결할 수 있습니다."
        ),
    },
    "mcp": {
        "label": "MCP 서버",
        "icon": "thunderbolt",
        "color": "var(--cyan-7)",
        "desc": (
            "Model Context Protocol 서버. 직접 운영하는 로컬 서버는 프로토콜로 공개할 수 있고, "
            "외부에서 공개된 MCP는 URL로 등록할 수 있습니다."
        ),
    },
}


def _count_by(agents: list[Agent], key: str, name: str, *, scalar: bool = False) -> int:
    """이름이 에이전트 *활성* config 배열(또는 스칼라 값)에 포함된 횟수(usedBy 배지용).

    배열 멤버십은 references._config_has로 위임(삭제 가드와 판정 로직 단일화, 드리프트 0).
    스펙 121 이후 삭제 가드(agents_referencing)도 **활성 config만** 세므로 배지와 답하는 질문이
    일치한다(과거 예엔 삭제만 버전까지 세던 어긋남을 121이 해소)."""
    total = 0
    for agent in agents:
        config = agent.config or {}
        if scalar:
            if config.get(key) == name:
                total += 1
        elif _config_has(config, key, name):
            total += 1
    return total


@router.get("/blocks")
async def get_blocks(
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> dict[str, Any]:
    agents = list((await session.execute(select(Agent))).scalars().all())

    prompts = list((await session.execute(select(Prompt))).scalars().all())
    memory_types = list((await session.execute(select(MemoryType))).scalars().all())
    collections = list(
        (
            await session.execute(
                select(Collection).options(selectinload(Collection.embedding_model))
            )
        )
        .scalars()
        .all()
    )
    mcp_servers = list((await session.execute(select(McpServer))).scalars().all())

    prompt_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,  # 설명(스펙 210)
            "tone": row.tone,
            "body": row.body,
            "usedBy": _count_by(agents, "prompt", row.name, scalar=True),
            "updated": _iso(row.updated_at),  # 수정일 배선(스펙 216) — 프론트 fmtTime이 친화 표기
            "version": row.version,  # 스펙 369
            **_audit_json(row),  # 감사 4값(스펙 344)
        }
        for row in prompts
    ]
    memory_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "key": row.key,
            "scope": row.scope,
            "body": row.body,
            "usedBy": _count_by(agents, "memories", row.name),
            "updated": "—",  # 메모리 타입은 읽기 전용(시스템 enum, spec 016) — 수정 N/A(스펙 216)
            **_audit_json(row),  # 감사 4값(스펙 344)
        }
        for row in memory_types
    ]
    embedding_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "kind": row.kind,  # document|entity(스펙 149)
            "model": row.embedding_model.name if row.embedding_model else "",
            "dims": row.dims,
            "docs": row.doc_count,
            "chunks": row.chunk_count,
            "chunkSize": row.chunk_size,
            "chunkOverlap": row.chunk_overlap,
            "status": row.status,
            "body": row.description,
            "usedBy": _count_by(agents, "vectorTables", row.name),
            "updated": "—",
            **_audit_json(row),  # 감사 4값(스펙 344)
        }
        for row in collections
    ]
    mcp_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,  # 설명(스펙 210)
            "source": row.source,
            "transport": row.transport,
            "url": row.url,
            "endpoint": row.endpoint,
            "tools": row.tools,
            "enabledTools": row.enabled_tools,
            "toolsMeta": row.tools_meta,  # 도구 메타(스펙 151) — 상세 드로어 카드용
            "status": row.status,
            "published": row.published,
            "served_url": _mcp_served_url(
                row
            ),  # 서빙 URL(스펙 156) — custom+정의보유만, 그 외 None
            "auth": _mcp_auth_masked(row),
            **_audit_json(row),  # 감사 4값(스펙 344)
            "usedBy": _count_by(agents, "mcps", row.name),
            "updated": _iso(row.updated_at),  # 수정일 배선(스펙 216)
            "version": row.version,  # 스펙 369
            "owner_id": row.owner_id,  # 스펙 112
            "can_manage": may_manage(row.owner_id, principal),  # 스펙 114 — UI 편집/삭제 표시 파생
        }
        for row in mcp_servers
    ]

    return {
        "prompt": {**_CATEGORY_META["prompt"], "items": prompt_items},
        "memory": {**_CATEGORY_META["memory"], "items": memory_items},
        "embedding": {**_CATEGORY_META["embedding"], "items": embedding_items},
        "mcp": {**_CATEGORY_META["mcp"], "items": mcp_items},
    }
