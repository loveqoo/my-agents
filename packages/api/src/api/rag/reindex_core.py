"""재인덱싱 코어(CAS 락·상태 전이·원자 스왑·이력) — shared.py에서 분할(스펙 398 P6, 순수 이동).

**락 응집 계약**(codex 398 함정 1): _acquire_reindex_lock의 원자 UPDATE와 _LOCKABLE_STATUSES는
같은 모듈에 동거(상수만 딴 데 남기면 최위험). 상태 전이(reindexing→ready/error ·
parsing→embedding→ready/error)는 ingest_core와 맞물림 — _reject_inflight_ingest는 parsing**과**
embedding 둘 다 본다(스펙 334 codex P1).
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto, rag_ingest
from ..models import (
    RAG_EMBED_DIMS,
    Chunk,
    Collection,
    CollectionReindexEvent,
    Document,
    DocumentBlob,
    ModelConfig,
)
from ..schemas import ReindexIn
from .embedding_models import _validate_embedding_model

# 재인덱싱 락 획득이 허용되는 컬렉션 상태(진행 중/삭제 상태는 제외).
_LOCKABLE_STATUSES = ("empty", "ready", "error")


def _reject_if_reindexing(c: Collection) -> None:
    """잠금 중 접근 차단(no silent) — 검색/인제스트/수정/삭제 진입 가드에서 호출."""
    if c.status == "reindexing":
        raise HTTPException(
            status_code=409, detail="컬렉션 재인덱싱이 진행 중입니다 — 잠시 후 다시 시도하세요."
        )


async def _acquire_reindex_lock(session: AsyncSession, cid: uuid.UUID) -> bool:
    """CAS 잠금 — status를 원자적으로 reindexing 전환(check-then-act 경합 회피). 영향 행 1=획득."""
    res = await session.execute(
        update(Collection)
        .where(Collection.id == cid, Collection.status.in_(_LOCKABLE_STATUSES))
        .values(status="reindexing")
    )
    await session.commit()
    return res.rowcount == 1


async def _set_collection_status(session: AsyncSession, cid: uuid.UUID, status: str) -> None:
    await session.execute(update(Collection).where(Collection.id == cid).values(status=status))
    await session.commit()


async def _embed_with_model(model: ModelConfig, chunks: list[str]) -> list:
    """명시 모델로 청크 임베딩(재인덱싱 — _embed_chunks는 컬렉션 자기 모델 고정이라 별도).
    같은 차원(RAG_EMBED_DIMS) 재인덱싱 불변식: 출력 차원이 저장소 고정 차원과 달라도 중단."""
    ep = model.provider
    if ep is None:
        raise rag_ingest.IngestError("대상 임베딩 모델의 provider가 없습니다.")
    vectors = await rag_ingest.embed_texts(
        ep.base_url, crypto.decrypt(ep.api_key), model.model_id, chunks
    )
    bad = next((len(v) for v in vectors if len(v) != RAG_EMBED_DIMS), None)
    if bad is not None:
        raise rag_ingest.IngestError(
            f"임베딩 차원({bad})이 저장소 차원({RAG_EMBED_DIMS})과 다릅니다 — 재인덱싱 중단(차원 고정)."
        )
    return vectors


async def _record_reindex_event(
    session: AsyncSession,
    cid: uuid.UUID,
    from_model: ModelConfig | None,
    to_model: ModelConfig | None,
    from_size: int,
    from_overlap: int,
    to_size: int,
    to_overlap: int,
    chunk_count: int,
    status: str,
    error: str | None,
    owner_id: str | None,
) -> None:
    """재인덱싱 이력 1건 — 성공/실패 모두(no silent). 모델 삭제 후에도 이름 박제로 계보."""
    session.add(
        CollectionReindexEvent(
            collection_id=cid,
            from_model_id=from_model.id if from_model else None,
            from_model_name=from_model.name if from_model else None,
            to_model_id=to_model.id if to_model else None,
            to_model_name=to_model.name if to_model else None,
            from_chunk_size=from_size,
            from_chunk_overlap=from_overlap,
            to_chunk_size=to_size,
            to_chunk_overlap=to_overlap,
            chunk_count=chunk_count,
            status=status,
            error=error,
            owner_id=owner_id,
        )
    )
    await session.commit()


async def _do_reindex(
    session: AsyncSession,
    c: Collection,
    target_model: ModelConfig,
    target_model_id: uuid.UUID,
    chunk_change: bool,
    new_size: int,
    new_overlap: int,
) -> int:
    """잠금 상태에서 호출 — 새 벡터/청크를 **먼저 전량 계산(txn 미보유)** 후 한 트랜잭션으로 원자
    스왑. 실패 시 원 상태 온전(반쪽 금지). 반환: 결과 chunk_count."""
    if not chunk_change:
        # 모델만 교체: 기존 청크 text를 새 모델로 재임베딩(순서 보존, 재청킹 아님).
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.text)
                .where(Chunk.collection_id == c.id)
                .order_by(Chunk.ordinal)
            )
        ).all()
        # 무중단(스펙 313): 읽기 스냅샷을 먼저 닫고(commit) HTTP 임베딩을 트랜잭션 밖에서 수행 →
        # 뒤이은 UPDATE+커밋만 짧은 쓰기 트랜잭션. MVCC상 동시 검색은 이 커밋 전까지 옛 임베딩을 본다.
        await session.commit()
        if rows:
            vectors = await _embed_with_model(target_model, [t for _id, t in rows])
            for (chunk_id, _t), v in zip(rows, vectors, strict=True):
                await session.execute(update(Chunk).where(Chunk.id == chunk_id).values(embedding=v))
        await session.execute(
            update(Collection)
            .where(Collection.id == c.id)
            .values(embedding_model_id=target_model_id)
        )
        await session.commit()  # ← 원자 스왑 커밋: 검색이 이 순간 새 임베딩으로 전환(반쪽 불가)
        return len(rows)

    # 재청킹(문서형): 각 문서 원본 blob에서 재분할 → 재임베딩 → 청크 교체. 전량 계산 먼저.
    docs = (
        (await session.execute(select(Document).where(Document.collection_id == c.id)))
        .scalars()
        .all()
    )
    rebuilt: list[tuple[Document, list[str], list]] = []
    total = 0
    for doc in docs:
        blob = await session.get(DocumentBlob, doc.id)
        if blob is None:  # 사전 가드에서 걸러지지만 방어(경합 삭제 등)
            raise rag_ingest.IngestError(f"문서 '{doc.filename}'의 원본이 없어 재청킹 불가.")
        text = rag_ingest.extract_text(doc.filename, doc.content_type, blob.data)
        new_chunks = rag_ingest.chunk_text(text, new_size, new_overlap)
        if not new_chunks:
            raise rag_ingest.IngestError(f"문서 '{doc.filename}' 재청킹 결과가 비었습니다.")
        vectors = await _embed_with_model(target_model, new_chunks)
        rebuilt.append((doc, new_chunks, vectors))
        total += len(new_chunks)
    # 원자 스왑: 기존 청크 전량 삭제 → 새 청크 삽입 → 문서/컬렉션 갱신 → 1회 커밋. 무중단(스펙 313):
    # HTTP 임베딩은 위 루프에서 이미 끝났고 여기서 처음 쓰기 락을 잡으므로, 동시 검색은 이 커밋
    # 전까지 옛 청크를, 커밋 순간부터 새 청크를 본다(MVCC 스냅샷 — 반쪽 불가·리더 블로킹 없음).
    await session.execute(delete(Chunk).where(Chunk.collection_id == c.id))
    for doc, new_chunks, vectors in rebuilt:
        for i, (t, v) in enumerate(zip(new_chunks, vectors, strict=True)):
            session.add(
                Chunk(
                    document_id=doc.id,
                    collection_id=c.id,
                    ordinal=i,
                    text=t,
                    meta=None,  # 재청킹은 문서형만 — 엔티티 meta 없음
                    embedding=v,
                )
            )
        doc.chunk_count = len(new_chunks)
    await session.execute(
        update(Collection)
        .where(Collection.id == c.id)
        .values(
            embedding_model_id=target_model_id,
            chunk_size=new_size,
            chunk_overlap=new_overlap,
            chunk_count=total,
        )
    )
    await session.commit()
    return total


async def _resolve_reindex_model(
    session: AsyncSession, c: Collection, body: ReindexIn
) -> tuple[ModelConfig, uuid.UUID, bool]:
    """모델 교체 요청 해석+검증(스펙 312) → (대상 모델, 대상 id, 변경 여부).
    미지정이면 현 모델 유지. 차원은 probe 실측으로 저장소(1024)와 일치해야(가드1 재사용)."""
    if body.embedding_model_id is None:
        return c.embedding_model, c.embedding_model_id, False
    m = await _validate_embedding_model(session, body.embedding_model_id)  # 생성과 공유(스펙 375)
    return m, m.id, body.embedding_model_id != c.embedding_model_id


def _resolve_rechunk(c: Collection, body: ReindexIn) -> tuple[bool, int, int]:
    """재청킹 요청 해석+검증(스펙 312) → (변경 여부, 새 크기, 새 겹침). 엔티티는 재청킹 불가."""
    rechunk = body.chunk_size is not None or body.chunk_overlap is not None
    new_size = body.chunk_size if body.chunk_size is not None else c.chunk_size
    new_overlap = body.chunk_overlap if body.chunk_overlap is not None else c.chunk_overlap
    if rechunk and c.kind != "document":
        raise HTTPException(
            status_code=400,
            detail="청크 크기·겹침 재인덱싱은 문서형 컬렉션만 가능합니다(엔티티는 1행=1청크).",
        )
    return (
        rechunk and (new_size != c.chunk_size or new_overlap != c.chunk_overlap),
        new_size,
        new_overlap,
    )


async def _reject_inflight_ingest(session: AsyncSession, cid: uuid.UUID) -> None:
    """인제스트 진행 중(parsing **또는 embedding** — 스펙 334 배경 잡, codex 334 P1)이면 409.
    embedding을 빼면: 배경 잡이 임베딩하는 동안 재인덱싱이 시작·완료(락 해제)된 뒤 늦은
    _finalize_ingest가 조건부 UPDATE(status != reindexing)를 통과해 옛 모델 벡터/중복 청크가
    스왑 밖에 커밋된다. (사전 검사~CAS 사이 미시 경합 창은 정직 경계 — 단일 프로세스 dev 도구.)"""
    in_flight = await session.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.collection_id == cid, Document.status.in_(("parsing", "embedding")))
    )
    if in_flight:
        raise HTTPException(
            status_code=409, detail="인제스트가 진행 중입니다 — 완료 후 다시 시도하세요."
        )


async def _reject_blobless_docs(session: AsyncSession, cid: uuid.UUID) -> None:
    """재청킹 전제 검증(스펙 312) — 원본 blob 없는 문서가 있으면 400(no silent, 어느 문서인지 표기)."""
    docs = (
        await session.execute(
            select(Document.id, Document.filename).where(Document.collection_id == cid)
        )
    ).all()
    if not docs:
        return
    have = set(
        (
            await session.execute(
                select(DocumentBlob.document_id).where(
                    DocumentBlob.document_id.in_([d.id for d in docs])
                )
            )
        )
        .scalars()
        .all()
    )
    missing = [d.filename for d in docs if d.id not in have]
    if missing:
        shown = ", ".join(missing[:5]) + (" 외" if len(missing) > 5 else "")
        raise HTTPException(
            status_code=400,
            detail=f"원본이 저장되지 않은 문서가 있어 재청킹할 수 없습니다({shown}). 재업로드가 필요합니다.",
        )
