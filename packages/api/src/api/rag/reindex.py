"""rag.reindex — 라우트 핸들러(스펙 381 분할). 서비스/헬퍼는 shared."""

import asyncio
import contextlib
import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import rag_ingest
from ..auth import current_principal
from ..db import SessionLocal, get_or_404, get_session
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
from .embedding_models import _load_collection
from .reindex_core import (
    _acquire_reindex_lock,
    _do_reindex,
    _record_reindex_event,
    _reject_blobless_docs,
    _reject_if_reindexing,
    _reject_inflight_ingest,
    _resolve_rechunk,
    _resolve_reindex_model,
    _set_collection_status,
)
from .router import router


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
    # 취소 해제용 스칼라 박제(스펙 434) — ORM 객체는 세션이 죽으면 못 읽는다(발자국 소실 실측).
    _cancel_snap = {
        "from_model_id": from_model.id if from_model else None,
        "from_model_name": from_model.name if from_model else None,
        "to_model_id": target_model.id if target_model else None,
        "to_model_name": target_model.name if target_model else None,
        "from_size": from_size,
        "from_overlap": from_overlap,
        "new_size": new_size,
        "new_overlap": new_overlap,
        "owner": owner_of(principal),
    }
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
    except BaseException:
        # 취소(CancelledError)·기타 BaseException — **잠금은 어떤 종료 경로로도 반드시 푼다**(스펙 434,
        # codex 433 P2). 종전엔 except Exception만 있어 클라이언트 이탈·종료 신호가 오면 status가
        # 'reindexing'에 갇혀 그 컬렉션의 편집·업로드·재인덱싱이 **재기동 전까지 409**였다.
        # 데이터는 미커밋 스왑이라 롤백으로 원 상태 온전(스펙 312 원자성) → 상태는 ready가 정확
        # (부팅 스윕 _recover_stale_reindex와 같은 근거). 취소 컨텍스트에선 현재 세션이 이미 죽었을 수
        # 있어 **새 세션 + shield**로 해제한다(스펙 403 shielded_release 선례). 원래 예외는 재전파.
        await asyncio.shield(_release_lock_after_cancel(cid, _cancel_snap))
        raise
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


async def _release_lock_after_cancel(
    cid: uuid.UUID,
    snap: dict,
) -> None:
    """취소 시 잠금 해제 + 발자국(스펙 434) — **새 세션**으로(요청 세션은 취소로 죽었을 수 있음).

    `snap`은 **잠금 시점에 박제한 스칼라**(모델 id·name·청크 파라미터·owner) — ORM 객체를 넘기면
    죽은 세션에 묶여 속성 접근이 터지고(그 예외를 suppress가 삼켜) 발자국이 조용히 사라진다
    (실측으로 잡음: 이력 0건 → 스칼라 박제로 교정. 스펙 331 "세션 만료 전 스칼라 박제"와 같은 결).

    best-effort: 해제·기록이 실패해도 원래 예외 전파를 막지 않는다(부팅 스윕이 마지막 그물).
    status는 아직 reindexing일 때만 되돌린다(다른 주체가 이미 정리했으면 덮지 않음)."""
    with contextlib.suppress(Exception):
        async with SessionLocal() as s2:
            res = await s2.execute(
                update(Collection)
                .where(Collection.id == cid, Collection.status == "reindexing")
                .values(status="ready")
            )
            await s2.commit()
            if res.rowcount:  # 우리가 실제로 푼 경우만 이력 기록(중복 발자국 방지)
                s2.add(
                    CollectionReindexEvent(
                        collection_id=cid,
                        from_model_id=snap["from_model_id"],
                        from_model_name=snap["from_model_name"],
                        to_model_id=snap["to_model_id"],
                        to_model_name=snap["to_model_name"],
                        from_chunk_size=snap["from_size"],
                        from_chunk_overlap=snap["from_overlap"],
                        to_chunk_size=snap["new_size"],
                        to_chunk_overlap=snap["new_overlap"],
                        chunk_count=0,
                        status="error",
                        error="취소됨(클라이언트 이탈·서버 종료) — 데이터는 원 상태 유지, 잠금 해제됨",
                        owner_id=snap["owner"],
                    )
                )
                await s2.commit()


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
