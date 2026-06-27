"""빌딩 블록 카탈로그 CRUD + 관리자 UI 집계 (REST).

페르소나·메모리타입·권한·MCP 서버의 전체 CRUD와, 관리자 콘솔이 한 번에 읽는 5개
카테고리 집계(`GET /blocks`)를 제공한다. embedding 카테고리는 RAG 컬렉션(스펙 036)을
읽기 전용으로 비춘다 — 컬렉션 CRUD/인제스트는 `rag.py`(`/collections`)가 담당한다.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import get_session
from .models import Agent, Collection, McpServer, MemoryType, Permission, Persona
from .schemas import (
    McpPublishIn,
    McpServerIn,
    McpServerOut,
    MemoryTypeIn,
    MemoryTypeOut,
    PermissionIn,
    PermissionOut,
    PersonaIn,
    PersonaOut,
)

router = APIRouter(tags=["blocks"])


# ----------------------------- 페르소나 -----------------------------
@router.get("/personas", response_model=list[PersonaOut])
async def list_personas(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(Persona))
    return result.scalars().all()


@router.post("/personas", response_model=PersonaOut, status_code=201)
async def create_persona(body: PersonaIn, session: AsyncSession = Depends(get_session)) -> Any:
    obj = Persona(**body.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/personas/{id}", response_model=PersonaOut)
async def get_persona(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.put("/personas/{id}", response_model=PersonaOut)
async def update_persona(
    id: uuid.UUID, body: PersonaIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    for key, value in body.model_dump().items():
        setattr(obj, key, value)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.delete("/personas/{id}", status_code=204)
async def delete_persona(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await session.get(Persona, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(obj)
    await session.commit()


# ----------------------------- 메모리 타입 -----------------------------
@router.get("/memory-types", response_model=list[MemoryTypeOut])
async def list_memory_types(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(MemoryType))
    return result.scalars().all()


@router.post("/memory-types", response_model=MemoryTypeOut, status_code=201)
async def create_memory_type(
    body: MemoryTypeIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = MemoryType(**body.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/memory-types/{id}", response_model=MemoryTypeOut)
async def get_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(MemoryType, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.put("/memory-types/{id}", response_model=MemoryTypeOut)
async def update_memory_type(
    id: uuid.UUID, body: MemoryTypeIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(MemoryType, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    for key, value in body.model_dump().items():
        setattr(obj, key, value)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.delete("/memory-types/{id}", status_code=204)
async def delete_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await session.get(MemoryType, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(obj)
    await session.commit()


# 벡터 테이블 CRUD는 RAG 컬렉션(스펙 036)으로 대체 — rag.py(`/collections`)가 담당.
# embedding 카테고리 집계는 get_blocks에서 Collection을 읽기 전용으로 비춘다.


# ----------------------------- 권한 -----------------------------
@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(Permission))
    return result.scalars().all()


@router.post("/permissions", response_model=PermissionOut, status_code=201)
async def create_permission(
    body: PermissionIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = Permission(**body.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/permissions/{id}", response_model=PermissionOut)
async def get_permission(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(Permission, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.put("/permissions/{id}", response_model=PermissionOut)
async def update_permission(
    id: uuid.UUID, body: PermissionIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(Permission, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    for key, value in body.model_dump().items():
        setattr(obj, key, value)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.delete("/permissions/{id}", status_code=204)
async def delete_permission(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await session.get(Permission, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(obj)
    await session.commit()


# ----------------------------- MCP 서버 -----------------------------
@router.get("/mcp-servers", response_model=list[McpServerOut])
async def list_mcp_servers(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(McpServer))
    return result.scalars().all()


@router.post("/mcp-servers", response_model=McpServerOut, status_code=201)
async def create_mcp_server(
    body: McpServerIn, session: AsyncSession = Depends(get_session)
) -> Any:
    data = body.model_dump()
    data["enabled_tools"] = body.enabled_tools or body.tools
    obj = McpServer(**data)
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/mcp-servers/{id}", response_model=McpServerOut)
async def get_mcp_server(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.put("/mcp-servers/{id}", response_model=McpServerOut)
async def update_mcp_server(
    id: uuid.UUID, body: McpServerIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    for key, value in body.model_dump().items():
        setattr(obj, key, value)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.delete("/mcp-servers/{id}", status_code=204)
async def delete_mcp_server(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(obj)
    await session.commit()


@router.put("/mcp-servers/{id}/publish", response_model=McpServerOut)
async def publish_mcp_server(
    id: uuid.UUID, body: McpPublishIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    obj.published = body.published
    await session.commit()
    await session.refresh(obj)
    return obj


# ----------------------------- 집계 (관리자 UI) -----------------------------
_CATEGORY_META: dict[str, dict[str, str]] = {
    "persona": {
        "label": "페르소나",
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
    "permission": {
        "label": "권한",
        "icon": "global",
        "color": "var(--geekblue-6)",
        "desc": (
            "에이전트에 부여되는 범위 한정 권한. 각 권한엔 승인자가 반드시 있습니다 — "
            "사용자는 대화 중 인라인 확인, 관리자는 승인 큐로 라우팅(체크포인트에서 일시정지). "
            "승인자를 지정하지 않으면 기본값은 '사용자' 승인입니다."
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
    """이름이 에이전트 config 배열(또는 스칼라 값)에 포함된 횟수."""
    total = 0
    for agent in agents:
        config = agent.config or {}
        value = config.get(key)
        if scalar:
            if value == name:
                total += 1
        elif isinstance(value, list) and name in value:
            total += 1
    return total


@router.get("/blocks")
async def get_blocks(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    agents = list((await session.execute(select(Agent))).scalars().all())

    personas = list((await session.execute(select(Persona))).scalars().all())
    memory_types = list((await session.execute(select(MemoryType))).scalars().all())
    collections = list(
        (
            await session.execute(
                select(Collection).options(selectinload(Collection.embedding_model))
            )
        ).scalars().all()
    )
    permissions = list((await session.execute(select(Permission))).scalars().all())
    mcp_servers = list((await session.execute(select(McpServer))).scalars().all())

    persona_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "tone": row.tone,
            "body": row.body,
            "usedBy": _count_by(agents, "persona", row.name, scalar=True),
            "updated": "—",
        }
        for row in personas
    ]
    memory_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "key": row.key,
            "scope": row.scope,
            "body": row.body,
            "usedBy": _count_by(agents, "memories", row.name),
            "updated": "—",
        }
        for row in memory_types
    ]
    embedding_items = [
        {
            "id": str(row.id),
            "name": row.name,
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
        }
        for row in collections
    ]
    permission_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "scope": row.scope,
            "approver": row.approver,
            "body": row.body,
            "usedBy": _count_by(agents, "permissions", row.name),
            "updated": "—",
        }
        for row in permissions
    ]
    mcp_items = [
        {
            "id": str(row.id),
            "name": row.name,
            "source": row.source,
            "transport": row.transport,
            "url": row.url,
            "endpoint": row.endpoint,
            "tools": row.tools,
            "enabledTools": row.enabled_tools,
            "status": row.status,
            "published": row.published,
            "auth": row.auth,
            "usedBy": _count_by(agents, "mcps", row.name),
            "updated": "—",
        }
        for row in mcp_servers
    ]

    return {
        "persona": {**_CATEGORY_META["persona"], "items": persona_items},
        "memory": {**_CATEGORY_META["memory"], "items": memory_items},
        "embedding": {**_CATEGORY_META["embedding"], "items": embedding_items},
        "permission": {**_CATEGORY_META["permission"], "items": permission_items},
        "mcp": {**_CATEGORY_META["mcp"], "items": mcp_items},
    }
