"""RAG 컬렉션 + 문서 인제스트 라우터 (스펙 036, P2-a 쓰기 경로).

컬렉션 CRUD + 파일 업로드 인제스트(파싱→청킹→임베딩→pgvector 적재) + 차원 점검.
retrieval(질의·유사도 검색·에이전트 도구 배선)은 037. 비밀(provider api_key)은 백엔드 전용.

차원 트랩 대응 — DB↔임베딩 모델 차이 3중 가드(스펙 020 함정3, no silent death):
  1) 생성: 임베딩 모델 probe → 실측 dims가 저장소 차원(RAG_EMBED_DIMS)과 다르면 409.
  2) 인제스트: 임베딩 벡터 길이 != Collection.dims면 status=error(메시지 보존), insert 0.
  3) 점검: GET /{id}/health — DB 컬럼/Collection 박제/모델 probe 3자 비교, drift 노출.
"""

import asyncio
import contextlib
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import crypto, events, rag_ingest
from ..db import SessionLocal
from ..model_registry import _probe
from ..models import (
    RAG_EMBED_DIMS,
    Chunk,
    Collection,
    CollectionReindexEvent,
    Document,
    DocumentBlob,
    ModelConfig,
    User,
)
from ..ownership import assert_may_manage
from ..schemas import (
    ReindexIn,
)

router = APIRouter(prefix="/collections", tags=["rag"])


_SCHEMA_MAX_CHARS = 20_000  # 스키마 직렬화 캡 — 거대 스키마의 행당 검증 비용 폭주 방지(codex 149)
_SCHEMA_BANNED_KEYS = ("pattern", "patternProperties")  # 정규식 키워드 금지(v1)


def _has_banned_key(node: object) -> str | None:
    """스키마 트리에서 금지 키워드 탐색 — 병적 정규식(`^(a+)+$` 류)이 행 전수 검증에서 CPU를
    폭주시키는 ReDoS 표면을 등록 시점에 차단(codex 149 High). v1 경계: 정규식 제약 미지원."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _SCHEMA_BANNED_KEYS:
                return k
            found = _has_banned_key(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _has_banned_key(item)
            if found:
                return found
    return None


def _check_entity_schema(schema: dict | None, kind: str) -> None:
    """entity_schema 입력 검증(스펙 149) — 스키마 자체가 유효한 JSON Schema인지 등록 시점에 확인
    (업로드 때 처음 터지면 원인 추적이 어렵다). 문서형에 스키마를 주면 400(의미 없음)."""
    if schema is None:
        return
    if kind != "entity":
        raise HTTPException(
            status_code=400, detail="entity_schema는 엔티티 컬렉션에만 설정할 수 있습니다."
        )
    import json

    import jsonschema

    if len(json.dumps(schema)) > _SCHEMA_MAX_CHARS:
        raise HTTPException(
            status_code=400, detail=f"JSON Schema가 너무 큽니다(최대 {_SCHEMA_MAX_CHARS}자)."
        )
    banned = _has_banned_key(schema)
    if banned:
        raise HTTPException(
            status_code=400,
            detail=f"JSON Schema의 '{banned}' 키워드는 지원하지 않습니다(정규식 제약은 v1 미지원 — 검증 비용 경계).",
        )
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise HTTPException(
            status_code=400, detail=f"JSON Schema가 유효하지 않습니다: {exc.message[:200]}"
        ) from exc


# 업로드 상한 — `await file.read()`는 전체를 메모리로 올리므로 무제한이면 단일/동시 업로드로 OOM.
# 기본 25MB, RAG_MAX_UPLOAD_MB로 조정. 초과 시 413(적재 전 차단).
MAX_UPLOAD_BYTES = int(os.environ.get("RAG_MAX_UPLOAD_MB", "25")) * 1024 * 1024

# 재인덱싱 락 획득이 허용되는 컬렉션 상태(진행 중/삭제 상태는 제외).
_LOCKABLE_STATUSES = ("empty", "ready", "error")


def _dim_mismatch(probed: int | None, target: int) -> str | None:
    """probe 실측 차원이 저장소 차원과 불일치하면 사유 문자열, 아니면 None(미상도 통과).

    probe 실패(None)는 막지 않는다 — 임베딩 서버가 잠시 죽어도 컬렉션 생성은 되게 하고,
    실제 불일치는 인제스트 시점(가드2)·health(가드3)에서 잡는다.
    """
    if probed is not None and probed != target:
        return (
            f"임베딩 모델의 출력 차원({probed})이 RAG 저장소 차원({target})과 다릅니다. "
            f"저장소(rag_chunks)는 vector({target})로 고정돼 있어 적재할 수 없습니다. "
            f"{target}차원 임베딩 모델을 선택하거나, 관리자에게 저장소 차원 정책 변경을 요청하세요."
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


async def _validate_embedding_model(session: AsyncSession, model_id: uuid.UUID) -> ModelConfig:
    """임베딩 모델 해석+검증(스펙 375·캠페인 374 T1-2) — 컬렉션 생성·재인덱싱 모델 선택 공유 단일 출처.

    이전엔 create_collection과 _resolve_reindex_model이 kind 강제·probe·차원 검사를 각각 복제해
    한쪽 규칙이 바뀌면 드리프트(codex 리뷰 P1). 규칙: 존재(400)·kind=embedding(400)·provider가
    있으면 probe 실측 차원이 저장소 고정 차원과 일치(불일치 409). provider 부재(레거시)는 probe
    생략 — _dim_mismatch가 '미상 통과' 규칙을 이미 가짐. 반환=검증된 모델.

    주의: 검색 시점 완전성 가드(search_collection의 em.kind 검사, 072 P2)는 실패 모드·메시지가 달라
    여기 합치지 않는다."""
    m = await _embedding_model(session, model_id)
    if m is None:
        raise HTTPException(status_code=400, detail="임베딩 모델을 찾을 수 없습니다.")
    if m.kind != "embedding":
        raise HTTPException(status_code=400, detail="임베딩(kind=embedding) 모델만 쓸 수 있습니다.")
    if m.provider is not None:  # 같은 차원(RAG_EMBED_DIMS)만 — probe 실측
        probe = await _probe(
            m.provider.base_url, crypto.decrypt(m.provider.api_key), m.model_id, "embedding"
        )
        msg = _dim_mismatch(probe.dims, RAG_EMBED_DIMS)
        if msg:
            raise HTTPException(status_code=409, detail=msg)
    return m


# ----------------------------- 컬렉션 CRUD -----------------------------


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
    _persist_chunks가 조건부 UPDATE(status != reindexing)를 통과해 옛 모델 벡터/중복 청크가
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


async def resolve_search_collection(session: AsyncSession, cid: uuid.UUID) -> dict:
    """검색 가능한 컬렉션 해석(시험 엔드포인트·평가 러너 공용 — 스펙 140에서 추출, 시맨틱 불변).
    완전성/kind 가드 포함, 실패는 HTTPException(404/400). api_key는 백엔드 전용 복호화."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    em = c.embedding_model
    ep = em.provider if em else None
    if em is None or ep is None or not ep.base_url or not em.model_id:
        raise HTTPException(
            status_code=400,
            detail="이 컬렉션은 임베딩 모델/provider 설정이 불완전해 검색할 수 없습니다.",
        )
    # kind 가드(적대 리뷰 072 P2): 모델 수정으로 컬렉션 참조 모델이 chat 등으로 바뀌면, 완전성만
    # 보면 통과해 임베딩 시도 → provider 502로 뭉개진다. embedding 모델이 아니면 설정 오류 400으로 명확히.
    if em.kind != "embedding":
        raise HTTPException(
            status_code=400,
            detail=f"컬렉션의 모델이 임베딩(kind=embedding)이 아닙니다(현재 kind={em.kind}). 검색할 수 없습니다.",
        )
    return {
        "id": c.id,
        "name": c.name,
        "embed_base_url": ep.base_url,
        "embed_api_key": crypto.decrypt(ep.api_key),  # 백엔드 전용 — 응답 미노출
        "embed_model_id": em.model_id,
    }


# ----------------------------- 문서 인제스트 -----------------------------


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


async def _content_length_guard(request: Request) -> None:
    """PUT 본문 크기 선검사(codex 331 P2) — Pydantic이 JSON을 파싱하기 *전에* Content-Length로
    거대 요청을 차단한다(파싱 후 len 검사만 있으면 이미 메모리에 올라온 뒤라 상한이 방어가 아님).
    **정직 경계**: Content-Length 없는 chunked 전송은 이 선검사를 우회한다(h11 수신 자체의 누적
    상한은 플랫폼 전역 미들웨어 몫 — 인증 필수 admin 표면이라 수용, 본검사 len(data)가 이중 그물)."""
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES + 65536:  # JSON 이스케이프 여유
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"본문이 너무 큽니다(최대 {limit_mb}MB).")
