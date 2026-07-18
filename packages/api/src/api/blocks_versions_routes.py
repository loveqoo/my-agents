"""블록 버전 이력 라우트(스펙 369) — blocks.py에서 분할(스펙 393 P2, 순수 이동).

5종 공유 제네릭 이력 조회. 파사드는 blocks.py(재수출 계약).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .block_versions import BLOCK_KINDS
from .db import get_session
from .models import BlockVersion
from .schemas import BlockVersionOut

router = APIRouter(tags=["blocks"])


@router.get("/block-versions/{kind}/{block_pk}", response_model=list[BlockVersionOut])
async def list_block_versions(
    kind: str, block_pk: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Any:
    """블록 이력 목록(최신순) — 5종 공유 제네릭(스펙 369 §4). kind 오탈자는 404."""
    if kind not in BLOCK_KINDS:
        raise HTTPException(status_code=404, detail=f"알 수 없는 블록 종류: {kind}")
    rows = await session.execute(
        select(BlockVersion)
        .where(BlockVersion.kind == kind, BlockVersion.block_pk == block_pk)
        .order_by(BlockVersion.version.desc())
    )
    return rows.scalars().all()


@router.get("/block-versions/{kind}/{block_pk}/{version}", response_model=BlockVersionOut)
async def get_block_version(
    kind: str, block_pk: uuid.UUID, version: int, session: AsyncSession = Depends(get_session)
) -> Any:
    if kind not in BLOCK_KINDS:
        raise HTTPException(status_code=404, detail=f"알 수 없는 블록 종류: {kind}")
    row = await session.scalar(
        select(BlockVersion).where(
            BlockVersion.kind == kind,
            BlockVersion.block_pk == block_pk,
            BlockVersion.version == version,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="그 버전의 이력이 없습니다.")
    return row
