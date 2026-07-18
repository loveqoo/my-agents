"""문서 인제스트 코어(파싱→청킹→임베딩→원자 적재) — shared.py에서 분할(스펙 398 P5, 순수 이동).

배경 인제스트(스펙 334)·실패 마킹·좀비 스윕. _execute_ingest의 외곽 try 범위는 계약(축소 시
parsing 영구 잔류 재발 — codex 398 함정 3). _persist_chunks의 조건부 UPDATE 선행은 재인덱싱
경합의 P0 유실 방지 계약(스펙 312 F1). sweep_zombie_ingests는 main lifespan 소비(api.rag 재수출).
"""

import asyncio
import contextlib
import uuid

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto, events, rag_ingest
from ..db import SessionLocal
from ..models import RAG_EMBED_DIMS, Chunk, Collection, Document, DocumentBlob, User
from ..ownership import assert_may_manage
from .embedding_models import _load_collection


def _doc_editable(c: Collection, doc: Document, has_blob: bool) -> tuple[bool, str | None]:
    """편집 가능 판정(단일 출처, 스펙 331) → (editable, 불가 사유). 목록·조회·수정 세 입구가 공유.
    엔티티도 편집 가능(스펙 332 — JSONL 행 단위, 저장 시 행 계약+entity_schema 검증 fail-closed)."""
    if c.kind not in ("document", "entity"):
        # kind 화이트리스트(codex 332 P3) — DB 컬럼은 String(20)이라 미지/레거시 값이 문서형 청킹
        # 경로로 흘러들지 않게 fail-closed.
        return False, f"알 수 없는 컬렉션 종류({c.kind}) — 편집할 수 없습니다."
    if doc.status in ("parsing", "embedding"):
        # 배경 인제스트 진행 중(스펙 334) — 지금 편집하면 잡의 적재와 스왑이 충돌(이중 청크).
        return False, "아직 처리 중인 문서입니다 — 임베딩이 끝나면 편집할 수 있습니다."
    if c.kind == "document" and rag_ingest.is_pdf(doc.filename, doc.content_type):
        return (
            False,
            "PDF는 편집할 수 없습니다 — 수정본을 재업로드하세요(추출 평문 편집은 원본과 어긋남).",
        )
    if not has_blob:
        return (
            False,
            "원본이 보존되지 않은 문서입니다(스펙 312 이전 인제스트) — 재업로드하면 편집 가능.",
        )
    return True, None


def _parse_entity_rows(c: Collection, data: bytes) -> list[tuple[str, dict]] | None:
    """엔티티 컬렉션이면 파싱된 (텍스트, 메타) 행 목록, 아니면 None.

    엔티티 컬렉션(스펙 149): Document 영속화 **전에** 행 전수 파싱·검증 — 형식 위반은 error 문서를
    남기지 않고 400으로 즉시 거부(fail-closed: 소스=SQL 추출물, 위반=파이프라인 버그. 부분 스킵은
    비즈니스 데이터의 조용한 유실). 행 번호가 detail에 담긴다."""
    if c.kind != "entity":
        return None
    try:
        return rag_ingest.parse_entity_lines(data, schema=c.entity_schema)
    except rag_ingest.EntityParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _split_chunks(
    c: Collection, doc: Document, data: bytes, entity_rows: list[tuple[str, dict]] | None
) -> tuple[list[str], list[dict | None]]:
    """청크·메타 목록 생성 → (chunks, metas). 빈 문서는 IngestError."""
    if entity_rows is not None:
        # 엔티티: 1행=1청크(분할 없음), metadata 동반(스펙 149)
        chunks = [t for t, _m in entity_rows]
        metas: list[dict | None] = [m for _t, m in entity_rows]
    else:
        text = rag_ingest.extract_text(doc.filename, doc.content_type, data)
        chunks = rag_ingest.chunk_text(text, c.chunk_size, c.chunk_overlap)
        metas = [None] * len(chunks)
    if not chunks:
        raise rag_ingest.IngestError("청크가 생성되지 않았습니다(빈 문서).")
    return chunks, metas


async def _embed_chunks(c: Collection, chunks: list[str]) -> list:
    """청크 임베딩 → 벡터 목록. provider 부재·차원 불일치는 IngestError."""
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
    return vectors


async def _persist_chunks(
    session: AsyncSession,
    c: Collection,
    doc: Document,
    chunks: list[str],
    metas: list[dict | None],
    vectors: list,
) -> None:
    """청크 insert + 문서/컬렉션 집계 갱신 후 커밋(반환 없음 — doc 제자리 갱신).

    **재인덱싱 경합 차단(스펙 312, codex F1)**: 집계 UPDATE를 청크 insert *앞에서* 조건부
    (`status != 'reindexing'`)로 먼저 실행한다. (1) 그 UPDATE가 컬렉션 행을 잠가 동시 재인덱싱 CAS를
    직렬화하고, (2) 영향 행 0이면(재인덱싱 시작됨) 청크를 넣기 전에 취소한다 — 재인덱싱이 스왑에서
    지우지 못할 청크가 커밋돼 유실되는 P0 데이터 손실을 막는다. 무조건 status='ready'로 덮어 잠금을
    푸는 문제도 사라진다(집계는 여전히 원자 증분이라 동시 인제스트는 그대로 지원)."""
    res = await session.execute(
        update(Collection)
        .where(Collection.id == c.id, Collection.status != "reindexing")
        .values(
            chunk_count=Collection.chunk_count + len(chunks),
            doc_count=Collection.doc_count + 1,
            status="ready",
        )
    )
    if res.rowcount == 0:
        # 재인덱싱이 시작됨(또는 컬렉션 소멸) — 이 인제스트 청크는 스왑 밖이라 무효. 넣지 않고 취소.
        raise rag_ingest.IngestError(
            "재인덱싱이 진행 중이라 인제스트를 취소했습니다 — 완료 후 다시 업로드하세요."
        )
    for i, (t, v, m) in enumerate(zip(chunks, vectors, metas, strict=True)):
        session.add(
            Chunk(
                document_id=doc.id,
                collection_id=c.id,
                ordinal=i,
                text=t,
                meta=m,  # 엔티티 metadata(스펙 149) — 문서형은 None
                embedding=v,
            )
        )
    doc.chunk_count = len(chunks)
    doc.status = "ready"
    await session.commit()
    await session.refresh(doc)


async def _mark_ingest_error(
    session: AsyncSession, doc_id: uuid.UUID, exc: Exception
) -> Document | None:
    """부분 적재 롤백 후 문서를 status=error로 박제 → 갱신된 문서(소실 시 None).

    IngestError 외(crypto.decrypt RuntimeError·commit DB 오류 등)도 문서를 parsing에 방치하거나
    500으로 흘리지 않는다. 비밀이 메시지에 섞일 수 있는 예외는 일반화해 노출 차단."""
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


async def _execute_ingest(
    doc_id: uuid.UUID,
    cid: uuid.UUID,
    data: bytes,
    entity_rows: list[tuple[str, dict]] | None,
) -> None:
    """배경 인제스트(스펙 334) — 청킹(to_thread)→임베딩(배치)→원자 적재. 실패=status error 박제.

    재시작 유실은 부팅 스윕(sweep_zombie_ingests)이 정직 박제하고, 재인덱싱 경합은
    _persist_chunks의 조건부 UPDATE(312 F1)+재인덱싱 사전 검사(parsing/embedding 409)가 막는다.
    문서가 그새 삭제되면 조용히 종료(CASCADE로 흔적 없음 — 정상 레이스)."""
    try:
        async with SessionLocal() as s:
            c = await _load_collection(s, cid)
            doc = await s.get(Document, doc_id)
            if c is None or doc is None:
                return  # 접수 직후 컬렉션/문서 삭제 레이스 — 남길 상태 행이 없다
            base = {  # 이벤트 공통(스펙 335) — 세션 만료 전에 스칼라 박제
                "type": "ingest",
                "document_id": str(doc_id),
                "collection_id": str(cid),
                "filename": doc.filename,
                "collection": c.name,
            }
            try:
                # CPU 구간(PDF 추출·청킹)은 스레드로 — 이벤트 루프 정지 방지(스펙 334).
                chunks, metas = await asyncio.to_thread(_split_chunks, c, doc, data, entity_rows)
                doc.status = "embedding"  # 상태 전이 — UI 폴링이 진행을 보인다
                await s.commit()
                vectors = await _embed_chunks(c, chunks)
                await _persist_chunks(s, c, doc, chunks, metas, vectors)
                events.publish({**base, "status": "ready", "chunks": len(chunks)})
            except Exception as exc:
                marked = await _mark_ingest_error(s, doc_id, exc)
                # error 문구는 박제본(비밀 일반화 완료)을 재사용 — 이벤트로 비밀이 새지 않는다.
                events.publish(
                    {
                        **base,
                        "status": "error",
                        "error": (marked.error if marked else None) or "인제스트 실패",
                    }
                )
    except Exception as exc:  # 세션 진입/초기 조회 실패(codex 334 P2) — parsing 영구 잔류 방지
        with contextlib.suppress(Exception):  # best-effort 박제(그마저 실패면 부팅 스윕이 그물)
            async with SessionLocal() as s2:
                await _mark_ingest_error(s2, doc_id, exc)


async def sweep_zombie_ingests() -> int:
    """startup 정리(스펙 334, eval 좀비 스윕 미러) — 배경 인제스트는 재시작을 못 넘기므로 부팅
    시점의 parsing/embedding 문서는 전부 죽은 처리다. error로 정직 박제(영원한 '처리 중' 방지).
    blob은 보존돼 재업로드 없이 재시도할 근거가 남는다(재시도 버튼은 OUT 씨앗)."""
    async with SessionLocal() as s:
        rows = (
            (await s.execute(select(Document).where(Document.status.in_(("parsing", "embedding")))))
            .scalars()
            .all()
        )
        for doc in rows:
            doc.status = "error"
            doc.error = "서버 재시작으로 처리가 중단되었습니다 — 다시 업로드하세요"
        if rows:
            await s.commit()
        return len(rows)


async def _load_editable_doc(
    session: AsyncSession, cid: uuid.UUID, doc_id: uuid.UUID, principal: User | str
) -> tuple[Collection, Document, DocumentBlob | None]:
    """편집 입구 공통 게이트(GET/PUT 미러) — 404 fold(비소유·불일치 존재 비노출) → 소유자/특권."""
    doc = await session.get(Document, doc_id)
    if doc is None or doc.collection_id != cid:
        raise HTTPException(status_code=404, detail="not found")
    col = await _load_collection(session, cid)
    if col is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(col, principal)  # 원문 열람=편집 권한과 동급(소유자/특권, 스펙 112)
    blob = await session.get(DocumentBlob, doc_id)
    return col, doc, blob
