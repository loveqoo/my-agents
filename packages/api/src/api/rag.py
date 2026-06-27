"""RAG 컬렉션 + 문서 인제스트 라우터 (스펙 036, P2-a 쓰기 경로).

컬렉션 CRUD + 파일 업로드 인제스트(파싱→청킹→임베딩→pgvector 적재) + 차원 점검.
retrieval(질의·유사도 검색·에이전트 도구 배선)은 037. 비밀(provider api_key)은 백엔드 전용.

차원 트랩 대응 — DB↔임베딩 모델 차이 3중 가드(스펙 020 함정3, no silent death):
  1) 생성: 임베딩 모델 probe → 실측 dims가 저장소 차원(RAG_EMBED_DIMS)과 다르면 409.
  2) 인제스트: 임베딩 벡터 길이 != Collection.dims면 status=error(메시지 보존), insert 0.
  3) 점검: GET /{id}/health — DB 컬럼/Collection 박제/모델 probe 3자 비교, drift 노출.
"""

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto, rag_ingest
from .db import get_session
from .model_registry import _probe
from .models import RAG_EMBED_DIMS, Chunk, Collection, Document, ModelConfig
from .schemas import (
    CollectionHealth,
    CollectionIn,
    CollectionOut,
    CollectionUpdate,
    DocumentOut,
)
from .serializers import collection_to_out

router = APIRouter(prefix="/collections", tags=["rag"])

# 업로드 상한 — `await file.read()`는 전체를 메모리로 올리므로 무제한이면 단일/동시 업로드로 OOM.
# 기본 25MB, RAG_MAX_UPLOAD_MB로 조정. 초과 시 413(적재 전 차단).
MAX_UPLOAD_BYTES = int(os.environ.get("RAG_MAX_UPLOAD_MB", "25")) * 1024 * 1024


def _dim_mismatch(probed: int | None, target: int) -> str | None:
    """probe 실측 차원이 저장소 차원과 불일치하면 사유 문자열, 아니면 None(미상도 통과).

    probe 실패(None)는 막지 않는다 — 임베딩 서버가 잠시 죽어도 컬렉션 생성은 되게 하고,
    실제 불일치는 인제스트 시점(가드2)·health(가드3)에서 잡는다.
    """
    if probed is not None and probed != target:
        return (
            f"임베딩 모델의 출력 차원({probed})이 RAG 저장소 차원({target})과 다릅니다. "
            f"저장소(rag_chunks)는 vector({target})로 고정돼 있어 적재할 수 없습니다."
        )
    return None


async def _load_collection(session: AsyncSession, cid: uuid.UUID) -> Collection | None:
    return (
        await session.execute(
            select(Collection)
            .where(Collection.id == cid)
            .options(selectinload(Collection.embedding_model).selectinload(ModelConfig.provider))
        )
    ).scalar_one_or_none()


async def _embedding_model(session: AsyncSession, model_id: uuid.UUID) -> ModelConfig | None:
    return (
        await session.execute(
            select(ModelConfig)
            .where(ModelConfig.id == model_id)
            .options(selectinload(ModelConfig.provider))
        )
    ).scalar_one_or_none()


# ----------------------------- 컬렉션 CRUD -----------------------------
@router.get("", response_model=list[CollectionOut])
async def list_collections(session: AsyncSession = Depends(get_session)) -> list[CollectionOut]:
    rows = (
        await session.execute(
            select(Collection)
            .options(selectinload(Collection.embedding_model))
            .order_by(Collection.name)
        )
    ).scalars().all()
    return [collection_to_out(c) for c in rows]


@router.post("", response_model=CollectionOut, status_code=201)
async def create_collection(
    body: CollectionIn, session: AsyncSession = Depends(get_session)
) -> CollectionOut:
    m = await _embedding_model(session, body.embedding_model_id)
    if m is None:
        raise HTTPException(status_code=400, detail="임베딩 모델을 찾을 수 없습니다.")
    if m.kind != "embedding":
        raise HTTPException(status_code=400, detail="임베딩(kind=embedding) 모델만 컬렉션에 쓸 수 있습니다.")
    # 가드1 — 생성 시점 차원 점검(probe 실측 vs 저장소 고정 차원).
    if m.provider is not None:
        probe = await _probe(m.provider.base_url, crypto.decrypt(m.provider.api_key), m.model_id, "embedding")
        msg = _dim_mismatch(probe.dims, RAG_EMBED_DIMS)
        if msg:
            raise HTTPException(status_code=409, detail=msg)
    c = Collection(
        name=body.name,
        description=body.description,
        embedding_model_id=body.embedding_model_id,
        dims=RAG_EMBED_DIMS,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        status="empty",
    )
    session.add(c)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 컬렉션이 이미 있습니다.")
    return collection_to_out(await _load_collection(session, c.id))


@router.get("/{cid}", response_model=CollectionOut)
async def get_collection(cid: uuid.UUID, session: AsyncSession = Depends(get_session)) -> CollectionOut:
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    return collection_to_out(c)


@router.put("/{cid}", response_model=CollectionOut)
async def update_collection(
    cid: uuid.UUID, body: CollectionUpdate, session: AsyncSession = Depends(get_session)
) -> CollectionOut:
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    # 임베딩 모델·dims는 불변(차원 고정). 설명·청킹 설정만 갱신.
    if body.description is not None:
        c.description = body.description
    if body.chunk_size is not None:
        c.chunk_size = body.chunk_size
    if body.chunk_overlap is not None:
        c.chunk_overlap = body.chunk_overlap
    await session.commit()
    return collection_to_out(await _load_collection(session, c.id))


@router.delete("/{cid}", status_code=204)
async def delete_collection(cid: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    c = await session.get(Collection, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(c)  # 문서·청크 CASCADE 동반 삭제
    await session.commit()


@router.get("/{cid}/health", response_model=CollectionHealth)
async def collection_health(
    cid: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> CollectionHealth:
    """가드3 — DB 컬럼 / Collection 박제 / 현재 임베딩 모델 probe 차원 3자 정합 점검(읽기 전용)."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    model_dims: int | None = None
    if c.embedding_model is not None and c.embedding_model.provider is not None:
        p = c.embedding_model.provider
        probe = await _probe(p.base_url, crypto.decrypt(p.api_key), c.embedding_model.model_id, "embedding")
        model_dims = probe.dims
    db_ok = c.dims == RAG_EMBED_DIMS
    model_ok = model_dims is None or model_dims == c.dims
    consistent = db_ok and model_ok
    if not db_ok:
        detail = f"Collection.dims({c.dims})가 저장소 차원({RAG_EMBED_DIMS})과 다릅니다."
    elif model_dims is None:
        detail = "임베딩 모델 probe 실패 — 모델 차원 확인 불가(서버 미기동 가능)."
    elif not model_ok:
        detail = f"임베딩 모델 차원({model_dims})이 Collection.dims({c.dims})와 다릅니다 — 재인제스트 필요."
    else:
        detail = "정합(OK)."
    return CollectionHealth(
        collection_id=c.id,
        db_dims=RAG_EMBED_DIMS,
        collection_dims=c.dims,
        model_dims=model_dims,
        consistent=consistent,
        detail=detail,
    )


# ----------------------------- 문서 인제스트 -----------------------------
@router.get("/{cid}/documents", response_model=list[DocumentOut])
async def list_documents(cid: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    if await session.get(Collection, cid) is None:
        raise HTTPException(status_code=404, detail="not found")
    rows = (
        await session.execute(
            select(Document).where(Document.collection_id == cid).order_by(Document.created_at)
        )
    ).scalars().all()
    return rows


@router.post("/{cid}/documents", response_model=DocumentOut, status_code=201)
async def ingest_document(
    cid: uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """업로드 → 파싱 → 청킹 → 임베딩 → pgvector 적재(동기). 실패는 status=error로 보존."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")

    # 적재 전 크기 차단(OOM 방지). size 헤더가 있으면 read 전에, 없으면 read 후 이중 점검.
    limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {limit_mb}MB).")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {limit_mb}MB).")
    doc = Document(
        collection_id=c.id,
        filename=file.filename or "untitled",
        content_type=file.content_type,
        byte_size=len(data),
        status="parsing",
    )
    session.add(doc)
    await session.commit()  # 문서 행은 먼저 영속화(과정 중 죽어도 흔적 남김)
    await session.refresh(doc)
    doc_id = doc.id  # rollback 후 doc는 expire되므로 id를 미리 박제(동기 lazy-load 회피)

    try:
        text = rag_ingest.extract_text(doc.filename, doc.content_type, data)
        chunks = rag_ingest.chunk_text(text, c.chunk_size, c.chunk_overlap)
        if not chunks:
            raise rag_ingest.IngestError("청크가 생성되지 않았습니다(빈 문서).")
        ep = c.embedding_model.provider if c.embedding_model else None
        if ep is None:
            raise rag_ingest.IngestError("컬렉션의 임베딩 provider가 없습니다.")
        vectors = await rag_ingest.embed_texts(
            ep.base_url, crypto.decrypt(ep.api_key), c.embedding_model.model_id, chunks
        )
        # 가드2 — 인제스트 시점 차원 검증. 저장소 컬럼은 RAG_EMBED_DIMS로 고정이므로 그 값과,
        # 그리고 컬렉션 박제값(c.dims) 둘 다와 일치해야 한다. 둘이 어긋난 drift(c.dims != 컬럼)도
        # 차단해 잘못된 차원이 DB insert에서 500나는 일을 막는다(조용한 죽음 대신 status=error).
        bad = next((len(v) for v in vectors if len(v) != RAG_EMBED_DIMS or len(v) != c.dims), None)
        if bad is not None:
            raise rag_ingest.IngestError(
                f"임베딩 차원({bad})이 저장소 차원({RAG_EMBED_DIMS})/컬렉션 차원({c.dims})과 "
                "다릅니다 — 적재 중단(차원 고정)."
            )
        for i, (t, v) in enumerate(zip(chunks, vectors)):
            session.add(
                Chunk(
                    document_id=doc.id,
                    collection_id=c.id,
                    ordinal=i,
                    text=t,
                    embedding=v,
                    token_count=len(t.split()),
                )
            )
        doc.chunk_count = len(chunks)
        doc.status = "ready"
        # 집계 캐시는 원자적 SQL 증분 — 같은 컬렉션에 동시 인제스트해도 lost update 없음.
        await session.execute(
            update(Collection)
            .where(Collection.id == c.id)
            .values(
                chunk_count=Collection.chunk_count + len(chunks),
                doc_count=Collection.doc_count + 1,
                status="ready",
            )
        )
        await session.commit()
        await session.refresh(doc)
    except Exception as exc:  # noqa: BLE001 — 모든 실패를 status=error로 보존(no silent death)
        # IngestError 외(crypto.decrypt RuntimeError·commit DB 오류 등)도 문서를 parsing에 방치하거나
        # 500으로 흘리지 않는다. 비밀이 메시지에 섞일 수 있는 예외는 일반화해 노출 차단.
        await session.rollback()  # 부분 적재(청크/카운트) 되돌림 — 문서 행은 이미 커밋됨
        doc = await session.get(Document, doc_id)
        if doc is not None:
            doc.status = "error"
            doc.error = (
                str(exc)
                if isinstance(exc, rag_ingest.IngestError)
                else f"인제스트 실패: {type(exc).__name__}"
            )
            await session.commit()
            await session.refresh(doc)
    return doc


@router.delete("/{cid}/documents/{doc_id}", status_code=204)
async def delete_document(
    cid: uuid.UUID, doc_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.collection_id != cid:
        raise HTTPException(status_code=404, detail="not found")
    removed = doc.chunk_count
    await session.delete(doc)  # 청크 CASCADE 동반 삭제
    # 집계 캐시는 원자적 SQL 감소(greatest로 음수 방지). 마지막 문서가 빠지면 status=empty.
    await session.execute(
        update(Collection)
        .where(Collection.id == cid)
        .values(
            doc_count=func.greatest(Collection.doc_count - 1, 0),
            chunk_count=func.greatest(Collection.chunk_count - removed, 0),
            status=case((Collection.doc_count - 1 <= 0, "empty"), else_=Collection.status),
        )
    )
    await session.commit()
