"""rag.documents — 라우트 핸들러(스펙 381 분할). 서비스/헬퍼는 shared."""

import asyncio
import uuid
from typing import Any

from fastapi import Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import rag_ingest
from ..auth import current_principal
from ..background import spawn
from ..db import get_or_404, get_session
from ..models import (
    Chunk,
    Collection,
    Document,
    DocumentBlob,
    User,
)
from ..ownership import assert_may_manage
from ..schemas import (
    DocumentContentOut,
    DocumentEditIn,
    DocumentEditOut,
    DocumentOut,
    DocumentPageOut,
)
from ..sqlutil import like_escape
from .embedding_models import _load_collection
from .ingest_core import (
    _doc_editable,
    _embed_chunks,
    _execute_ingest,
    _load_editable_doc,
    _parse_entity_rows,
)
from .limits import MAX_UPLOAD_BYTES, _content_length_guard
from .reindex_core import _reject_if_reindexing
from .router import router


@router.get("/{cid}/documents", response_model=DocumentPageOut)
async def list_documents(
    cid: uuid.UUID,
    q: str | None = Query(None, max_length=500),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    session: AsyncSession = Depends(get_session),
    _principal: User | str = Depends(current_principal),
) -> Any:
    """문서 페이지 목록(스펙 128) — 문서는 증가 축이라 서버 페이지네이션 + 파일명 부분일치(q).

    세션(list_sessions)과 동형: LIMIT/OFFSET + count total + ilike(`like_escape` 재사용 — 정본 sqlutil).
    스코프(collection_id)는 SQL WHERE. 사용은 전부 공용(스펙 172) — 로그인한 누구나 문서 목록 조회
    가능(익명은 current_principal이 401). 존재 404만 유지(관리는 여전히 소유자만)."""
    col = await get_or_404(
        session, Collection, cid
    )  # 존재 404만(관리는 소유자만 — 아래 스코프 무관)
    # blob 보존 여부를 outerjoin으로 동반 조회(스펙 331 editable — 행별 재조회 없이 한 방).
    base = (
        select(Document, DocumentBlob.document_id.isnot(None))
        .outerjoin(DocumentBlob, DocumentBlob.document_id == Document.id)
        .where(Document.collection_id == cid)
    )
    if q and q.strip():
        base = base.where(Document.filename.ilike(f"%{like_escape(q.strip())}%", escape="\\"))
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        # id tiebreak — 같은 created_at(한 트랜잭션 일괄 인제스트)에서도 페이지가 결정적·비중복(127 원칙).
        await session.execute(
            base.order_by(Document.created_at, Document.id).offset(offset).limit(limit)
        )
    ).all()
    items = [
        DocumentOut.model_validate(doc).model_copy(
            update={"editable": _doc_editable(col, doc, has_blob)[0]}
        )
        for doc, has_blob in rows
    ]
    # 전역 처리 중 신호(스펙 334, codex P2) — 현재 페이지/검색어와 무관하게 컬렉션 전체 기준.
    processing = (
        await session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.collection_id == cid, Document.status.in_(("parsing", "embedding")))
        )
    ).scalar_one()
    return DocumentPageOut(items=items, total=total, processing=processing)


@router.post("/{cid}/documents", response_model=DocumentOut, status_code=201)
async def ingest_document(
    cid: uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> DocumentOut:
    """업로드 = **접수**(스펙 334): 파싱·형식 검증까지 동기(엔티티 위반=행 번호 400 계약 보존),
    오래 걸리는 임베딩+적재는 배경 잡 — 즉시 201(status=parsing) 반환, 상태 전이(parsing→
    embedding→ready/error)는 문서 목록으로 관찰. 실패는 status=error로 보존(no silent death)."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)
    _reject_if_reindexing(c)  # 재인덱싱 중 인제스트 차단(스펙 312 배타 잠금)

    # 적재 전 크기 차단(OOM 방지). size 헤더가 있으면 read 전에, 없으면 read 후 이중 점검.
    limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {limit_mb}MB).")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {limit_mb}MB).")

    # 엔티티 형식 위반은 여기서 400(스펙 149 계약 — 배경으로 밀면 400을 줄 수 없다). CPU 구간이라
    # to_thread — 수만 행 파싱·스키마 검증이 이벤트 루프를 정지시키지 않게(스펙 334).
    entity_rows = await asyncio.to_thread(_parse_entity_rows, c, data)

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
    doc_id = doc.id
    # 스펙 312: 원본 바이트 보존(재청킹 필수 — 청크 크기·겹침 변경 시 원본에서 다시 자른다).
    # 문서와 함께 영속(1:1). 인제스트가 뒤에서 실패해도 원본은 남아 재시도 근거가 된다.
    session.add(DocumentBlob(document_id=doc_id, data=data))
    await session.commit()

    # 임베딩+적재는 배경(스펙 334) — 접수 즉시 반환. 잡은 자기 세션을 연다(요청 세션은 곧 닫힘).
    spawn(_execute_ingest(doc_id, cid, data, entity_rows))
    return doc


@router.delete("/{cid}/documents/{doc_id}", status_code=204)
async def delete_document(
    cid: uuid.UUID,
    doc_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> None:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.collection_id != cid:
        raise HTTPException(status_code=404, detail="not found")
    col = await session.get(Collection, cid)
    assert_may_manage(col, principal)  # 컬렉션 소유자/특권만(스펙 112)
    if col is not None:
        _reject_if_reindexing(
            col
        )  # 재인덱싱 중 문서 삭제 차단(스펙 312 F3 — 잠금 해제·청크 유실 방지)
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


# ----------------------------- 문서 런타임 수정 (스펙 331) -----------------------------


@router.get("/{cid}/documents/{doc_id}/content", response_model=DocumentContentOut)
async def get_document_content(
    cid: uuid.UUID,
    doc_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> DocumentContentOut:
    """문서 원문 조회(스펙 331) — 편집 가능하면 text 동반, 아니면 editable=false+사유(정직 표면화)."""
    col, doc, blob = await _load_editable_doc(session, cid, doc_id, principal)
    editable, reason = _doc_editable(col, doc, blob is not None)
    if not editable:
        return DocumentContentOut(id=doc.id, filename=doc.filename, editable=False, reason=reason)
    assert blob is not None  # _doc_editable(has_blob=True) 보장
    try:
        text = blob.data.decode("utf-8")
    except UnicodeDecodeError:
        return DocumentContentOut(
            id=doc.id,
            filename=doc.filename,
            editable=False,
            reason="UTF-8 텍스트가 아닌 원본입니다 — 편집 불가.",
        )
    return DocumentContentOut(id=doc.id, filename=doc.filename, editable=True, text=text)


@router.put(
    "/{cid}/documents/{doc_id}/content",
    response_model=DocumentEditOut,
    dependencies=[Depends(_content_length_guard)],
)
async def update_document_content(
    cid: uuid.UUID,
    doc_id: uuid.UUID,
    body: DocumentEditIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> DocumentEditOut:
    """문서 수정 + 부분 재임베딩(스펙 331) — blob 교체 → 그 문서만 재청킹, **내용 동일 청크는
    기존 벡터 재사용**·변경 청크만 임베딩("해당 영역만"의 청크 입도 구현). 스왑은 한 트랜잭션
    (MVCC — 동시 검색은 커밋 순간 전환, 스펙 313 승계).

    동시성 경계: 편집 vs 편집은 last-write-wins(단일 사용자 admin 도구 — 낙관 잠금은 OUT).
    재인덱싱과의 경합은 사전 409 + 스왑 직전 조건부 UPDATE(스펙 312 codex F1 미러)로 이중 차단."""
    col, doc, blob = await _load_editable_doc(session, cid, doc_id, principal)
    _reject_if_reindexing(col)  # 재인덱싱 중 수정 차단(스펙 312 배타 잠금)
    editable, reason = _doc_editable(col, doc, blob is not None)
    if not editable:
        raise HTTPException(status_code=400, detail=reason)
    assert blob is not None

    data = body.text.encode("utf-8")
    limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"본문이 너무 큽니다(최대 {limit_mb}MB).")
    # 재청킹 — 엔티티(스펙 332)는 JSONL 행 파싱(1행=1청크+meta, 스키마 검증 fail-closed·위반 행
    # 번호 400 = 업로드 입구와 동일 계약), 문서형은 글자 분할. 이후 부분 재임베딩은 공통.
    entity_rows = _parse_entity_rows(col, data)
    if entity_rows is not None:
        new_chunks = [t for t, _m in entity_rows]
        new_metas: list[dict | None] = [m for _t, m in entity_rows]
    else:
        new_chunks = rag_ingest.chunk_text(body.text, col.chunk_size, col.chunk_overlap)
        new_metas = [None] * len(new_chunks)
    if not new_chunks:
        raise HTTPException(status_code=400, detail="청크가 생성되지 않았습니다(빈 문서).")

    # 부분 재임베딩 — 기존 청크 text→벡터 맵을 만들고, 텍스트가 같은 청크는 벡터 재사용.
    # 재청킹은 결정적(같은 텍스트→같은 청크)이라 수정 지점 주변(경계 밀림 포함)만 임베딩 비용 발생.
    old_rows = (
        await session.execute(
            select(Chunk.text, Chunk.embedding).where(Chunk.document_id == doc.id)
        )
    ).all()
    old_map = dict(old_rows)  # (text → 기존 벡터)
    # 통계는 **청크(occurrence) 기준**(codex 331 P2 — reused+reembedded==chunks 불변식): 같은 새
    # 텍스트가 문서 안에 두 번 나와도 둘 다 "재임베딩된 청크"다. 임베딩 *호출*은 유일화해 1회.
    reembedded = sum(1 for t in new_chunks if t not in old_map)
    reused = len(new_chunks) - reembedded
    missing = list(dict.fromkeys(t for t in new_chunks if t not in old_map))  # 호출용 유일화
    # 무중단(스펙 313): HTTP 임베딩은 트랜잭션 밖에서 끝내고 쓰기는 아래 스왑 한 번만.
    await session.commit()
    if missing:
        try:
            new_vectors = await _embed_chunks(col, missing)
        except rag_ingest.IngestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        old_map.update(zip(missing, new_vectors, strict=True))

    # 원자 스왑 — 조건부 UPDATE를 먼저(재인덱싱 CAS 직렬화 + 시작됐으면 취소, 312 codex F1). 이
    # UPDATE가 컬렉션 행을 잠근 뒤, 집계 증분은 스냅샷의 doc.chunk_count가 아니라 **실제 delete
    # rowcount**로 계산한다(codex 331 P1 — 동시 편집 시 임베딩 전 스냅샷 값이 stale해 집계가 어긋남).
    res = await session.execute(
        update(Collection)
        .where(Collection.id == cid, Collection.status != "reindexing")
        .values(status="ready")  # 문서가 있는 컬렉션의 불변 상태 — 값 변화 없이 행 잠금+검사
    )
    if res.rowcount == 0:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="재인덱싱이 진행 중이라 수정을 취소했습니다 — 완료 후 다시 시도하세요.",
        )
    deleted = (await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))).rowcount
    await session.execute(
        update(Collection)
        .where(Collection.id == cid)
        .values(chunk_count=func.greatest(Collection.chunk_count - deleted + len(new_chunks), 0))
    )
    for i, (t, m) in enumerate(zip(new_chunks, new_metas, strict=True)):
        session.add(
            Chunk(
                document_id=doc.id,
                collection_id=cid,
                ordinal=i,
                text=t,
                # 엔티티=행 metadata(스펙 332 — 텍스트 동일·meta만 변경이어도 여기서 갱신됨,
                # 벡터는 재사용). 문서형은 None.
                meta=m,
                embedding=old_map[t],
            )
        )
    doc.chunk_count = len(new_chunks)
    doc.byte_size = len(data)
    doc.status = "ready"
    doc.error = None
    blob.data = data  # 원본 교체 — 이후 재인덱싱·재편집의 근거(스펙 312 계약 유지)
    await session.commit()  # ← 스왑 커밋: 검색이 이 순간 새 내용으로 전환(반쪽 불가)
    await session.refresh(doc)
    out = DocumentOut.model_validate(doc).model_copy(update={"editable": True})
    return DocumentEditOut(
        document=out, chunks=len(new_chunks), reembedded=reembedded, reused=reused
    )
