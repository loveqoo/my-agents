"""문서 인제스트 코어(파싱→청킹→임베딩→원자 적재) — shared.py에서 분할(스펙 398 P5, 순수 이동).

배경 인제스트(스펙 334)·실패 마킹·좀비 스윕. _execute_ingest의 외곽 try 범위는 계약(축소 시
parsing 영구 잔류 재발 — codex 398 함정 3). _finalize_ingest의 조건부 UPDATE(말미, 스펙 432)는 재인덱싱
경합의 P0 유실 방지 계약(스펙 312 F1). sweep_zombie_ingests는 main lifespan 소비(api.rag 재수출).
"""

import asyncio
import contextlib
import os
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


async def _finalize_ingest(
    session: AsyncSession,
    c: Collection,
    doc: Document,
    total: int,
    *,
    used_model_id: uuid.UUID,
    used_chunk_size: int,
    used_chunk_overlap: int,
) -> None:
    """집계·상태 확정 + 커밋 — **재인덱싱 경합 차단(스펙 312 codex F1 → 432 말미 이동+재료 관문)**.

    관문 둘(rowcount=0이면 raise → 같은 트랜잭션의 flush 청크 전부 롤백 — 커밋 전 불가시):
    1. `status != 'reindexing'` — 재인덱싱 **진행 중**이면 취소(종전 F1).
    2. **사용 재료 일치**(codex 432 P0): 임베딩 구간 중 재인덱싱이 시작·완료(ready 복귀)까지 하면
       상태 검사만으론 통과한다 — 이 창의 절반은 종전(선행 UPDATE) 코드에도 있었다(임베딩이 잠금
       밖이었으므로). embedding_model_id·chunk_size·chunk_overlap이 **우리가 임베딩에 쓴 값 그대로**
       일 때만 커밋: 재인덱싱이 완주했어도 재료가 안 변했으면 우리 청크는 정합(같은 모델=같은 벡터,
       같은 청킹 정책)이라 허용, 모델/청킹이 바뀌었으면 옛 재료 청크가 새 스왑에 섞이므로 취소.
    종전 선행-UPDATE의 분 단위 컬렉션 행 잠금(재인덱싱 CAS 블록)은 여전히 소멸 — 잠금은 커밋 직전 찰나."""
    res = await session.execute(
        update(Collection)
        .where(
            Collection.id == c.id,
            Collection.status != "reindexing",
            Collection.embedding_model_id == used_model_id,
            Collection.chunk_size == used_chunk_size,
            Collection.chunk_overlap == used_chunk_overlap,
        )
        .values(
            chunk_count=Collection.chunk_count + total,
            doc_count=Collection.doc_count + 1,
            status="ready",
        )
    )
    if res.rowcount == 0:
        # 재인덱싱 진행 중이거나, 그새 재료(모델·청킹)가 바뀌었거나, 컬렉션 소멸 — 이 인제스트 청크는
        # 무효. raise가 커밋을 막아 flush분까지 전체 롤백(취소).
        raise rag_ingest.IngestError(
            "재인덱싱과 겹쳐 인제스트를 취소했습니다(컬렉션 설정 변경 가능성) — 다시 업로드하세요."
        )
    doc.chunk_count = total
    doc.status = "ready"
    # refresh 제거(codex 432 P1): commit 성공 후 refresh가 실패하면 _mark_ingest_error가 이미 커밋된
    # 문서를 error로 덮어 "error인데 청크는 검색됨" 반쪽 상태를 만들었다. 호출부는 refresh가 불필요
    # (이벤트 페이로드는 커밋 전 박제된 스칼라 사용).
    await session.commit()


async def _embed_persist_batched(
    session: AsyncSession,
    c: Collection,
    doc: Document,
    chunks: list[str],
    metas: list[dict | None],
) -> None:
    """임베딩→적재를 EMBED_BATCH(128) 단위로 흘려보낸다(스펙 432 — 전량 누적 소멸).

    실측(432): 종전 전량 경로(전 벡터 리스트 + 전량 ORM)는 21k 청크에 피크 Δ+1.75GB·잔류 +0.98GB.
    배치마다 임베딩→insert→flush→expunge로 벡터·ORM 상주를 배치 1개로 유계화. 트랜잭션은 하나
    (원자성 유지 — flush는 커밋 아님, 중간 실패 시 전체 롤백). 차원 검증(가드2)은 배치마다 동일.
    청크 문자열 목록은 그대로(업로드 캡 25MB로 유계 — 지배 항 아님)."""
    ep = c.embedding_model.provider if c.embedding_model else None
    if ep is None:
        raise rag_ingest.IngestError("컬렉션의 임베딩 provider가 없습니다.")
    api_key = crypto.decrypt(ep.api_key)
    model_id = c.embedding_model.model_id
    # 사용 재료 박제(codex 432 P0) — 임베딩 시작 시점의 모델·청킹. finalize가 이 값 그대로일 때만 커밋.
    used_model_pk = c.embedding_model_id
    used_chunk_size, used_chunk_overlap = c.chunk_size, c.chunk_overlap
    for start in range(0, len(chunks), rag_ingest.EMBED_BATCH):
        bc = chunks[start : start + rag_ingest.EMBED_BATCH]
        bm = metas[start : start + rag_ingest.EMBED_BATCH]
        vecs = await rag_ingest.embed_texts(ep.base_url, api_key, model_id, bc)
        bad = next((len(v) for v in vecs if len(v) != RAG_EMBED_DIMS or len(v) != c.dims), None)
        if bad is not None:
            raise rag_ingest.IngestError(
                f"임베딩 차원({bad})이 저장소 차원({RAG_EMBED_DIMS})/컬렉션 차원({c.dims})과 "
                "다릅니다 — 적재 중단(차원 고정)."
            )
        rows = [
            Chunk(
                document_id=doc.id,
                collection_id=c.id,
                ordinal=start + j,
                text=t,
                meta=m,  # 엔티티 metadata(스펙 149) — 문서형은 None
                embedding=v,
            )
            for j, (t, v, m) in enumerate(zip(bc, vecs, bm, strict=True))
        ]
        session.add_all(rows)
        await session.flush()
        for row in rows:  # identity map 참조 해제 — flush된 ORM이 상주하지 않게(메모리 유계의 반쪽)
            session.expunge(row)
    await _finalize_ingest(
        session,
        c,
        doc,
        len(chunks),
        used_model_id=used_model_pk,
        used_chunk_size=used_chunk_size,
        used_chunk_overlap=used_chunk_overlap,
    )


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


# 동시 인제스트 상한(스펙 432 B, 구남님 승인 기본 2) — spawn 무상한이라 동시 업로드 N개의 피크가
# 겹치던 것을 유계화. 대기 중 문서는 status=parsing(UI 폴링에 자연 표시). env로 조정.
def _ingest_concurrency() -> int:
    """RAG_INGEST_CONCURRENCY 정규화 — 0/음수/비정수는 기본 2로(codex 432 P1: 0이면 세마포어가 영구
    폐쇄돼 전 인제스트가 parsing에 고착 — 파괴적 노브 바닥, learning 037 결)."""
    try:
        return max(1, int(os.environ.get("RAG_INGEST_CONCURRENCY", "2")))
    except ValueError:
        return 2


_INGEST_SEM = asyncio.Semaphore(_ingest_concurrency())


async def _execute_ingest(
    doc_id: uuid.UUID,
    cid: uuid.UUID,
    data: bytes,
    entity_rows: list[tuple[str, dict]] | None,
) -> None:
    """배경 인제스트(스펙 334) — 청킹(to_thread)→임베딩(배치)→원자 적재. 실패=status error 박제.

    재시작 유실은 부팅 스윕(sweep_zombie_ingests)이 정직 박제하고, 재인덱싱 경합은
    _finalize_ingest의 조건부 UPDATE(312 F1→432 말미 이동)+재인덱싱 사전 검사(parsing/embedding 409)가 막는다.
    문서가 그새 삭제되면 조용히 종료(CASCADE로 흔적 없음 — 정상 레이스)."""
    try:
        async with _INGEST_SEM, SessionLocal() as s:
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
                await _embed_persist_batched(s, c, doc, chunks, metas)
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
