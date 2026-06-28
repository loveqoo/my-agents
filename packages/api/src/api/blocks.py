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

from . import crypto
from .db import get_session
from .models import Agent, Collection, McpServer, MemoryType, Permission, Persona
from .schemas import (
    McpDiscoverIn,
    McpDiscoverResult,
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
def _mcp_auth_masked(obj: McpServer) -> str | None:
    """저장된 auth(암호문)를 응답용 마스킹값으로 — 평문/암호문 절대 미노출(스펙 054 F, 누출-안전)."""
    return crypto.SECRET_MASK if obj.auth else None


def mcp_to_out(obj: McpServer) -> McpServerOut:
    """ORM → 응답 DTO. auth는 마스킹해 평문 토큰을 절대 흘리지 않는다."""
    return McpServerOut(
        id=obj.id,
        name=obj.name,
        source=obj.source,
        transport=obj.transport,
        url=obj.url,
        endpoint=obj.endpoint,
        tools=list(obj.tools or []),
        enabled_tools=list(obj.enabled_tools or []),
        status=obj.status,
        published=obj.published,
        auth=_mcp_auth_masked(obj),
    )


@router.get("/mcp-servers", response_model=list[McpServerOut])
async def list_mcp_servers(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(McpServer))
    return [mcp_to_out(o) for o in result.scalars().all()]


@router.post("/mcp-servers", response_model=McpServerOut, status_code=201)
async def create_mcp_server(
    body: McpServerIn, session: AsyncSession = Depends(get_session)
) -> Any:
    data = body.model_dump()
    data["enabled_tools"] = body.enabled_tools or body.tools
    # auth는 평문 입력 → Fernet 암호화 저장. 마스킹값이 들어오면(신규엔 없어야 함) 비워둔다.
    data["auth"] = None if (body.auth and crypto.is_masked(body.auth)) else crypto.encrypt(body.auth)
    obj = McpServer(**data)
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return mcp_to_out(obj)


@router.post("/mcp-servers/discover", response_model=McpDiscoverResult)
async def discover_mcp_tools(body: McpDiscoverIn) -> Any:
    """저장 전 폼에서 MCP 서버에 **실제로 붙어** 도구목록을 읽는다(부작용 0 — list만). 등록 자동채움용(스펙 054 E).

    SSRF: 연결 이전 `guard_url` — 사설/비-allowlist 대역은 **4xx로 거절**(보안 경계, 정상 연결실패와 구분).
    stdio는 유예 — http만 라이브 탐색. 비밀은 결과에 미포함(latency·도구이름만). 마스킹(•) auth는 헤더 생략.
    """
    import asyncio
    import time

    from langchain_mcp_adapters.client import MultiServerMCPClient

    from . import net_guard

    url = (body.url or "").strip()
    if body.transport != "http":
        return McpDiscoverResult(
            ok=False, reachable=False, detail="stdio transport는 라이브 탐색 미지원(유예)"
        )
    try:
        net_guard.guard_url(url)
    except net_guard.SsrfBlocked as exc:
        # 보안 경계 위반은 4xx(정상 연결실패의 ok=False와 구분) — 스펙 054 완료조건 ④.
        raise HTTPException(status_code=400, detail=str(exc)) from None

    headers: dict[str, str] = {}
    token = (body.auth or "").strip()
    if token and "•" not in token:  # 마스킹값(•)이면 헤더 생략(a2a_client 규칙)
        headers["Authorization"] = f"Bearer {token}"

    t0 = time.perf_counter()
    try:
        client = MultiServerMCPClient(
            {"probe": {
                "transport": "streamable_http", "url": url, "headers": headers or None,
                # 리다이렉트-SSRF 차단(적대 리뷰 H1) — runtime.build_mcp_tools와 동일 정책.
                "httpx_client_factory": net_guard.mcp_http_client_factory,
            }}
        )
        async with asyncio.timeout(15):
            tools = await client.get_tools(server_name="probe")
    except Exception:  # noqa: BLE001 — 연결/프로토콜 오류(상세 미노출, 비밀 에코 방지)
        ms = int((time.perf_counter() - t0) * 1000)
        return McpDiscoverResult(ok=False, reachable=False, latencyMs=ms, detail="연결 실패")
    ms = int((time.perf_counter() - t0) * 1000)
    names = [t.name for t in tools]
    return McpDiscoverResult(
        ok=True, reachable=True, tools=names, latencyMs=ms, detail=f"{len(names)}개 도구 발견"
    )


@router.get("/mcp-servers/{id}", response_model=McpServerOut)
async def get_mcp_server(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return mcp_to_out(obj)


@router.put("/mcp-servers/{id}", response_model=McpServerOut)
async def update_mcp_server(
    id: uuid.UUID, body: McpServerIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await session.get(McpServer, id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    data = body.model_dump()
    # auth 의미 구분(provider.api_key와 동형): None/마스킹 = 기존 암호화 토큰 보존,
    # 빈 문자열 = 명시적 제거, 그 외 = 새 평문 암호화. 마스킹값이 그대로 저장되는 버그 방지.
    auth_in = data.pop("auth", None)
    for key, value in data.items():
        setattr(obj, key, value)
    if auth_in is None or crypto.is_masked(auth_in):
        pass  # 보존
    elif auth_in == "":
        obj.auth = None
    else:
        obj.auth = crypto.encrypt(auth_in)
    await session.commit()
    await session.refresh(obj)
    return mcp_to_out(obj)


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
    return mcp_to_out(obj)


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
            "auth": _mcp_auth_masked(row),
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
