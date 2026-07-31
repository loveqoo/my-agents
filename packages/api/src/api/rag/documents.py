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
from ..db import SessionLocal, get_or_404, get_session
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
    ingest_progress,
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
            update={
                "editable": _doc_editable(col, doc, has_blob)[0],
                "progress": ingest_progress(doc.id),  # 스펙 435 — 진행 중이면 {done,total}
            }
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


@router.post("/{cid}/documents/{doc_id}/reingest", response_model=DocumentOut)
async def reingest_document(
    cid: uuid.UUID,
    doc_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> DocumentOut:
    """실패한 문서를 **보존된 원본으로** 다시 인제스트(스펙 435 A) — 재업로드 불요.

    원본 blob은 재청킹·편집 근거로 이미 영속돼 있다(스펙 312) → 실패 원인이 일시적(모델 서버 재기동·
    회로 열림 등)일 때 파일을 다시 올리게 하는 건 불필요한 마찰이었다.

    게이트: status=='error'만(성공·진행 중 재시도는 중복 적재라 400) · blob 존재 · 재인덱싱 중 409 ·
    관리 권한. 실행은 **업로드와 같은 경로**(_execute_ingest spawn)라 세마포어·배치 흘려보내기·재료
    관문(스펙 432/433)을 그대로 승계한다. 엔티티 컬렉션은 업로드와 동일하게 행 파싱을 재수행(위반=400).
    """
    col, doc, blob = await _load_editable_doc(session, cid, doc_id, principal)
    _reject_if_reindexing(col)  # 재인덱싱 중 인제스트 차단(스펙 312 배타 잠금)
    if doc.status != "error":
        raise HTTPException(
            status_code=400,
            detail=f"실패한 문서만 재시도할 수 있습니다(현재 상태: {doc.status}).",
        )
    if blob is None:
        raise HTTPException(status_code=400, detail="원본이 없어 재시도할 수 없습니다 — 다시 업로드하세요.")

    data = blob.data
    # 엔티티 형식 위반은 여기서 400(업로드와 같은 계약 — 배경으로 밀면 400을 줄 수 없다).
    entity_rows = await asyncio.to_thread(_parse_entity_rows, col, data)
    # 방어적 멱등: 실패분 청크가 남아 있으면 지우고 시작(432가 전체 롤백이라 보통 0건).
    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    doc.status = "parsing"
    doc.error = None
    await session.commit()
    await session.refresh(doc)
    spawn(_execute_ingest(doc.id, cid, data, entity_rows))
    return DocumentOut.model_validate(doc).model_copy(update={"editable": True})


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
    # 재사용 판정은 **텍스트 집합만으로**(스펙 433 — 벡터 컬럼 미조회): 종전엔 문서 전 청크의
    # text→벡터 맵을 메모리에 올려 피크가 문서 규모에 비례했다(업로드 캡 25MB면 인제스트급).
    # 벡터는 아래 스왑 루프가 **배치별로 DB에서** 가져온다(상주 유계).
    # 재사용 판정은 **텍스트 집합만**(스펙 433 — 벡터 컬럼 미조회로 문서 전 벡터 상주 소멸).
    old_texts = set(
        (await session.execute(select(Chunk.text).where(Chunk.document_id == doc.id))).scalars()
    )
    # 통계는 **청크(occurrence) 기준**(codex 331 P2 — reused+reembedded==chunks 불변식): 같은 새
    # 텍스트가 문서 안에 두 번 나와도 둘 다 "재임베딩된 청크"다.
    reembedded = sum(1 for t in new_chunks if t not in old_texts)
    reused = len(new_chunks) - reembedded
    # 무중단(스펙 313): 읽기 스냅샷을 닫고, 쓰기는 아래 스왑 한 트랜잭션·커밋 1회.
    await session.commit()

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
    # 옛 청크 삭제는 **문서 단위·선행 그대로**(codex 433 P1 교정): id 지정 삭제로 바꾸면 동시 편집
    # last-write-wins가 깨진다(대기하던 B가 A의 청크를 못 지워 A+B 공존·집계 과대). 문서 단위 DELETE는
    # 잠금을 얻은 쪽이 상대 청크까지 치워 LWW를 보존한다(스펙 331 경계 유지).
    deleted = (await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))).rowcount
    await session.execute(
        update(Collection)
        .where(Collection.id == cid)
        .values(chunk_count=func.greatest(Collection.chunk_count - deleted + len(new_chunks), 0))
    )
    # 배치 스왑(스펙 433): 배치마다 ①재사용 텍스트의 옛 벡터를 **별도 읽기 세션**에서 조회 — 우리
    # DELETE는 아직 미커밋이라 다른 세션 스냅샷엔 옛 행이 그대로 보인다(같은 text=같은 벡터라 값 동일)
    # ②미보유 텍스트만 임베딩 ③insert→flush→expunge → 벡터 상주가 배치 1개(문서 전 벡터 맵 소멸).
    # **정직한 변경**: 임베딩 호출 유일화가 "문서 전체"→"배치 내"로 축소(배치를 가로지르는 동일 신규
    # 텍스트는 재임베딩 가능 — 같은 텍스트=같은 벡터라 정합성 무영향, 비용만 미미 증가).
    # 재인덱싱 F1 가드(위 조건부 UPDATE)는 **선행 유지** — 편집은 문서 1개(유계)라 잠금 시간이 짧고
    # 안전 시맨틱(스펙 331/312)을 건드리지 않는 쪽을 택했다(432 인제스트와 다른 판단·의도적).
    for start in range(0, len(new_chunks), rag_ingest.EMBED_BATCH):
        bt = new_chunks[start : start + rag_ingest.EMBED_BATCH]
        bm = new_metas[start : start + rag_ingest.EMBED_BATCH]
        reuse_texts = [t for t in dict.fromkeys(bt) if t in old_texts]
        vec_map: dict[str, list] = {}
        if reuse_texts:
            async with SessionLocal() as rs:  # 읽기 전용 스냅샷 — 우리 미커밋 DELETE 무영향
                for _t, _v in (
                    await rs.execute(
                        select(Chunk.text, Chunk.embedding).where(
                            Chunk.document_id == doc.id, Chunk.text.in_(reuse_texts)
                        )
                    )
                ).all():
                    vec_map.setdefault(_t, _v)
        need = list(dict.fromkeys(t for t in bt if t not in vec_map))
        if need:
            try:
                fresh = await _embed_chunks(col, need)
            except rag_ingest.IngestError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            vec_map.update(zip(need, fresh, strict=True))
            del fresh
        added = [
            Chunk(
                document_id=doc.id,
                collection_id=cid,
                ordinal=start + j,
                text=t,
                # 엔티티=행 metadata(스펙 332 — 텍스트 동일·meta만 변경이어도 여기서 갱신됨,
                # 벡터는 재사용). 문서형은 None.
                meta=m,
                embedding=vec_map[t],
            )
            for j, (t, m) in enumerate(zip(bt, bm, strict=True))
        ]
        session.add_all(added)
        await session.flush()
        for row in added:  # identity map 해제(432 패턴) — flush된 ORM 상주 방지
            session.expunge(row)
        del added, vec_map
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
