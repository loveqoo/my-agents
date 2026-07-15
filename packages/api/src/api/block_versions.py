"""블록 버전 관문(스펙 369) — append-only 단조 불변 버전의 단일 진입점.

5종 블록(prompt·memory-type·mcp-server·model·provider)의 모든 콘텐츠 변경 경로가
`record_block_version`을 경유한다(PUT·재탐색 동기화·생성). 잡별 삽입 금지 — 미경유 mutate가
남으면 그 경로만 버전 없이 동작이 바뀐다(스펙 369 C6 전수 대장으로 확인).

경계(스펙 369 §2): payload = 동작을 결정하는 저작 내용만. 운영 상태(status·published·
is_default·meta)·비밀(api_key·auth)은 head 전용 — 이력에 비밀 잔존 금지, 운영 변경은 버전 무증가.
payload 정의는 이 모듈이 단일 출처(마이그레이션 SQL로 중복 정의하지 않는다 — drift 방지).
"""

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BlockVersion, McpServer, MemoryType, ModelConfig, Prompt, Provider


def _prompt_payload(o: Prompt) -> dict:
    return {"name": o.name, "description": o.description, "tone": o.tone, "body": o.body}


def _memory_type_payload(o: MemoryType) -> dict:
    return {"key": o.key, "name": o.name, "scope": o.scope, "body": o.body}


def _mcp_payload(o: McpServer) -> dict:
    # status(라이브 헬스)·published(서빙 토글)·auth(비밀)·owner_id(소유)는 제외.
    return {
        "name": o.name,
        "description": o.description,
        "source": o.source,
        "transport": o.transport,
        "url": o.url,
        "endpoint": o.endpoint,
        "tools": o.tools,
        "enabled_tools": o.enabled_tools,
        "tools_meta": o.tools_meta,
    }


def _model_payload(o: ModelConfig) -> dict:
    # is_default(포인터)·meta(카탈로그 캐시)는 제외.
    return {
        "name": o.name,
        "provider_id": str(o.provider_id),
        "model_id": o.model_id,
        "kind": o.kind,
        "params": o.params,
    }


def _provider_payload(o: Provider) -> dict:
    # api_key(비밀) 제외 — 키 로테이션은 운영 행위(버전 무증가, 이력에 비밀 잔존 금지).
    return {
        "name": o.name,
        "protocol": o.protocol,
        "base_url": o.base_url,
        "kind": o.kind,
        "description": o.description,
    }


BLOCK_KINDS: dict[str, tuple[type, Any]] = {
    "prompt": (Prompt, _prompt_payload),
    "memory-type": (MemoryType, _memory_type_payload),
    "mcp-server": (McpServer, _mcp_payload),
    "model": (ModelConfig, _model_payload),
    "provider": (Provider, _provider_payload),
}


def payload_for(kind: str, row: Any) -> dict:
    return BLOCK_KINDS[kind][1](row)


async def _latest(session: AsyncSession, kind: str, block_pk: uuid.UUID) -> BlockVersion | None:
    return await session.scalar(
        select(BlockVersion)
        .where(BlockVersion.kind == kind, BlockVersion.block_pk == block_pk)
        .order_by(BlockVersion.version.desc())
        .limit(1)
    )


async def record_block_version(session: AsyncSession, kind: str, row: Any) -> bool:
    """콘텐츠 변경 후·commit 전에 호출 — payload가 직전 버전과 다르면 head.version+1 + 이력 append.

    동일 payload(운영-only 변경·무변경 저장)는 no-op(버전 무증가). 이력이 아예 없으면 v1 기록
    (신규 생성·백필). 동시 편집은 UNIQUE(kind,block_pk,version)가 commit에서 막는다 → 409는
    호출부의 commit_or_409 몫. 반환: 버전이 올랐는가."""
    payload = payload_for(kind, row)
    last = await _latest(session, kind, row.id)
    if last is None:
        row.version = row.version or 1
        session.add(
            BlockVersion(kind=kind, block_pk=row.id, version=row.version, payload=payload)
        )
        return True
    if last.payload == payload:
        return False  # 저작 내용 동일 — 운영 변경/무변경 저장은 버전 무증가(스펙 369 C4)
    row.version = last.version + 1
    session.add(BlockVersion(kind=kind, block_pk=row.id, version=row.version, payload=payload))
    return True


async def delete_block_history(session: AsyncSession, kind: str, block_pk: uuid.UUID) -> None:
    """블록 삭제와 같은 트랜잭션에서 이력 정리(폴리모픽이라 FK cascade 불가)."""
    await session.execute(
        sa_delete(BlockVersion).where(
            BlockVersion.kind == kind, BlockVersion.block_pk == block_pk
        )
    )


async def ensure_v1_rows(session: AsyncSession) -> int:
    """이력 없는 블록에 v1 백필(멱등) — 부트·시드 공용. 기존 DB 이관과 처녀 빌드가 같은 불변식
    (블록 행 수 == 이력 보유 블록 수)에 도달한다. 반환: 새로 백필한 블록 수."""
    created = 0
    for kind, (model_cls, to_payload) in BLOCK_KINDS.items():
        have = {
            pk
            for (pk,) in (
                await session.execute(
                    select(BlockVersion.block_pk).where(BlockVersion.kind == kind).distinct()
                )
            ).all()
        }
        for row in (await session.execute(select(model_cls))).scalars():
            if row.id in have:
                continue
            row.version = row.version or 1
            session.add(
                BlockVersion(
                    kind=kind, block_pk=row.id, version=row.version, payload=to_payload(row)
                )
            )
            created += 1
    if created:
        await session.commit()
    return created


async def commit_or_409(session: AsyncSession, detail: str) -> None:
    """커밋하되 유니크 충돌(이름 중복·버전 레이스)은 409로 정직 변환."""
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail) from e


async def count_missing_history(session: AsyncSession) -> int:
    """검증용(C2) — 이력 없는 블록 수(0이어야 불변식 성립)."""
    missing = 0
    for kind, (model_cls, _) in BLOCK_KINDS.items():
        total = await session.scalar(select(func.count()).select_from(model_cls))
        with_hist = await session.scalar(
            select(func.count(BlockVersion.block_pk.distinct())).where(BlockVersion.kind == kind)
        )
        missing += (total or 0) - (with_hist or 0)
    return missing
