"""rag.reindex — 라우트 핸들러(스펙 381 분할). 서비스/헬퍼는 shared."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import rag_ingest
from ..auth import current_principal
from ..db import get_or_404, get_session
from ..models import (
    Collection,
    CollectionReindexEvent,
    User,
)
from ..ownership import assert_may_manage, owner_of
from ..schemas import (
    CollectionOut,
    ReindexEventOut,
    ReindexIn,
)
from ..serializers import collection_to_out
from .shared import (
    _acquire_reindex_lock,
    _do_reindex,
    _load_collection,
    _record_reindex_event,
    _reject_blobless_docs,
    _reject_if_reindexing,
    _reject_inflight_ingest,
    _resolve_rechunk,
    _resolve_reindex_model,
    _set_collection_status,
    router,
)


@router.post("/{cid}/reindex", response_model=CollectionOut)
async def reindex_collection(
    cid: uuid.UUID,
    body: ReindexIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> CollectionOut:
    """컬렉션 재인덱싱(스펙 312) — 임베딩 모델 교체(같은 차원 1024)와/또는 청크 크기·겹침 재청킹.
    재인덱싱 중 배타 잠금(다른 접근 409). 평가 이력은 보존(건드리지 않음).
    검증 4블록은 헬퍼로 분해(복잡도 게이트 rank D → 정비, 2026-07-14 — 시맨틱 불변)."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)
    _reject_if_reindexing(c)  # 이미 잠김이면 조기 거절(CAS로도 막지만 명확 메시지)

    target_model, target_model_id, model_change = await _resolve_reindex_model(session, c, body)
    chunk_change, new_size, new_overlap = _resolve_rechunk(c, body)
    if not model_change and not chunk_change:
        raise HTTPException(
            status_code=400,
            detail="변경할 내용이 없습니다(모델 또는 청크 크기·겹침 중 하나는 현재와 달라야 합니다).",
        )
    await _reject_inflight_ingest(session, cid)
    if chunk_change:
        await _reject_blobless_docs(session, cid)

    # ── 잠금 획득(CAS) → 원자 재인덱싱 → 해제(try/finally 결) ──
    from_model = c.embedding_model
    from_size, from_overlap = c.chunk_size, c.chunk_overlap
    if not await _acquire_reindex_lock(session, cid):
        raise HTTPException(
            status_code=409, detail="다른 재인덱싱이 진행 중이거나 컬렉션이 사용 중입니다."
        )
    try:
        count = await _do_reindex(
            session, c, target_model, target_model_id, chunk_change, new_size, new_overlap
        )
    except Exception as exc:
        await session.rollback()  # 반쪽 스왑 되돌림(원 청크·모델 온전)
        await _set_collection_status(session, cid, "error")
        detail = (
            str(exc)
            if isinstance(exc, rag_ingest.IngestError)
            else f"재인덱싱 실패: {type(exc).__name__}"
        )
        await _record_reindex_event(
            session,
            cid,
            from_model,
            target_model,
            from_size,
            from_overlap,
            new_size,
            new_overlap,
            0,
            "error",
            detail,
            owner_of(principal),
        )
        raise HTTPException(status_code=500, detail=detail) from exc
    await _set_collection_status(session, cid, "ready")
    await _record_reindex_event(
        session,
        cid,
        from_model,
        target_model,
        from_size,
        from_overlap,
        new_size,
        new_overlap,
        count,
        "ok",
        None,
        owner_of(principal),
    )
    updated = await _load_collection(session, cid)
    assert updated is not None
    return collection_to_out(updated)


@router.get("/{cid}/reindex-events", response_model=list[ReindexEventOut])
async def list_reindex_events(
    cid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _principal: User | str = Depends(current_principal),
) -> list[ReindexEventOut]:
    """재인덱싱 이력(최신순, 스펙 312) — 컬렉션 모델·청크 정책 계보."""
    await get_or_404(session, Collection, cid)  # 존재 확인
    rows = (
        (
            await session.execute(
                select(CollectionReindexEvent)
                .where(CollectionReindexEvent.collection_id == cid)
                .order_by(CollectionReindexEvent.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [ReindexEventOut.model_validate(r, from_attributes=True) for r in rows]


# ----------------------------- retrieval 시험(스펙 072) -----------------------------
