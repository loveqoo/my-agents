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
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto, events, rag_ingest
from .auth import current_principal
from .background import spawn
from .db import SessionLocal, get_or_404, get_session
from .model_registry import _probe
from .models import (
    RAG_EMBED_DIMS,
    Chunk,
    Collection,
    CollectionReindexEvent,
    Document,
    DocumentBlob,
    ModelConfig,
    User,
)
from .naming import validate_resource_name
from .ownership import assert_may_manage, may_manage, owner_of
from .references import agents_referencing, referenced_message
from .schemas import (
    CollectionHealth,
    CollectionIn,
    CollectionOut,
    CollectionSearchIn,
    CollectionSearchOut,
    CollectionUpdate,
    DocumentContentOut,
    DocumentEditIn,
    DocumentEditOut,
    DocumentOut,
    DocumentPageOut,
    ReindexEventOut,
    ReindexIn,
    SearchHit,
)
from .serializers import collection_to_out
from .sqlutil import like_escape

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


# ----------------------------- 컬렉션 CRUD -----------------------------
@router.get("", response_model=list[CollectionOut])
async def list_collections(
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> list[CollectionOut]:
    rows = (
        (
            await session.execute(
                select(Collection)
                .options(selectinload(Collection.embedding_model))
                .order_by(Collection.name)
            )
        )
        .scalars()
        .all()
    )
    outs = [collection_to_out(c) for c in rows]
    for out in outs:  # 스펙 114 — 관리 가능 여부 파생
        out.can_manage = may_manage(out.owner_id, principal)
    return outs


@router.post("", response_model=CollectionOut, status_code=201)
async def create_collection(
    body: CollectionIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> CollectionOut:
    err = validate_resource_name(body.name)  # 식별 이름 규칙(스펙 148)
    if err:
        raise HTTPException(status_code=400, detail=err)
    _check_entity_schema(body.entity_schema, body.kind)  # 스키마 자체 유효성(스펙 149)
    m = await _embedding_model(session, body.embedding_model_id)
    if m is None:
        raise HTTPException(status_code=400, detail="임베딩 모델을 찾을 수 없습니다.")
    if m.kind != "embedding":
        raise HTTPException(
            status_code=400, detail="임베딩(kind=embedding) 모델만 컬렉션에 쓸 수 있습니다."
        )
    # 가드1 — 생성 시점 차원 점검(probe 실측 vs 저장소 고정 차원).
    if m.provider is not None:
        probe = await _probe(
            m.provider.base_url, crypto.decrypt(m.provider.api_key), m.model_id, "embedding"
        )
        msg = _dim_mismatch(probe.dims, RAG_EMBED_DIMS)
        if msg:
            raise HTTPException(status_code=409, detail=msg)
    c = Collection(
        name=body.name,
        kind=body.kind,  # 종류 축(스펙 149) — 생성 후 불변
        entity_schema=body.entity_schema if body.kind == "entity" else None,
        description=body.description,
        embedding_model_id=body.embedding_model_id,
        dims=RAG_EMBED_DIMS,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        status="empty",
        owner_id=owner_of(principal),  # 생성 시 1회 스탬프(스펙 112)
    )
    session.add(c)
    try:
        await session.commit()
    except IntegrityError as dup:  # `err`(위 이름 검증 결과)와 섀도잉 금지 — mypy 타입 혼동 방지
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 컬렉션이 이미 있습니다.") from dup
    created = await _load_collection(session, c.id)
    assert created is not None  # 방금 커밋한 행의 재로드 — 동시 삭제 레이스 외엔 불가
    return collection_to_out(created)


@router.get("/{cid}", response_model=CollectionOut)
async def get_collection(
    cid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> CollectionOut:
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    out = collection_to_out(c)
    out.can_manage = may_manage(out.owner_id, principal)  # 스펙 114
    return out


@router.put("/{cid}", response_model=CollectionOut)
async def update_collection(
    cid: uuid.UUID,
    body: CollectionUpdate,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> CollectionOut:
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)
    _reject_if_reindexing(c)  # 재인덱싱 중 수정 차단(스펙 312 배타 잠금)
    # 임베딩 모델·dims·kind·**청크 정책**은 불변(스펙 198 — 청크 수정은 소급 안 되고 재청킹은 원본
    # 미저장이라 불가 → 수정 제거). 설명·엔티티 스키마만 갱신.
    if "entity_schema" in body.model_fields_set:
        # 명시적 null=스키마 제거(codex 149 — 오등록 스키마를 API로 해제 못 하면 업로드가 영구 잠김),
        # 미포함=미변경. 이후 업로드부터 적용(기존 행 재검증 없음 — 스펙 149). 문서형엔 400.
        if c.kind != "entity":
            raise HTTPException(
                status_code=400, detail="entity_schema는 엔티티 컬렉션에만 설정할 수 있습니다."
            )
        _check_entity_schema(body.entity_schema, "entity")
        c.entity_schema = body.entity_schema
    if body.description is not None:
        c.description = body.description
    # 스펙 198: 청크 크기·겹침 수정 제거(생성 후 불변). 구 클라이언트가 보내도 스키마에 필드가 없어 무시됨.
    await session.commit()
    updated = await _load_collection(session, c.id)
    assert updated is not None  # 위 404 가드로 존재 확인된 행의 재로드 — 동시 삭제 레이스 외엔 불가
    return collection_to_out(updated)


@router.delete("/{cid}", status_code=204)
async def delete_collection(
    cid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> None:
    c = await get_or_404(session, Collection, cid)
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)
    _reject_if_reindexing(c)  # 재인덱싱 중 삭제 차단(스펙 312 배타 잠금)
    # 참조 무결성(스펙 093): 이 컬렉션 name을 vectorTables에 담은 에이전트가 있으면 삭제 차단.
    # 삭제하면 config에 dangling name만 남아 런타임이 조용히 RAG 없이 동작(chat.py 미해석).
    refs = await agents_referencing(session, "vectorTables", c.name)
    if refs:
        raise HTTPException(status_code=409, detail=referenced_message(refs, "RAG 컬렉션"))
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
        probe = await _probe(
            p.base_url, crypto.decrypt(p.api_key), c.embedding_model.model_id, "embedding"
        )
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


# ----------------------------- 재인덱싱·재청킹(스펙 312) -----------------------------
# 배타 잠금: 재인덱싱 중 컬렉션 status='reindexing' → 검색·인제스트·수정·삭제·재인덱싱 전부 차단.
# 'reindexing'은 lockable에서 제외돼 이중 재인덱싱을 CAS가 원자적으로 막는다. 인제스트는 커밋 시점
# 조건부 UPDATE(_persist_chunks, status!='reindexing')로 경합을 닫는다(codex F1).
#
# 알려진 경계(codex 적대 리뷰 — 안전 위반 아닌 미문서 경계, 개인 단일 워커 배포 전제, 스펙 312 OUT):
#   F4: update/delete_collection의 _reject_if_reindexing은 point-in-time 가드(TOCTOU 창 존재).
#       reindex-vs-reindex는 CAS로 원자 배타지만, 관리 CRUD-vs-reindex는 best-effort(드문 관리 액션).
#   F5: 대상 모델 probe 실패(None)면 차원 검증을 통과시킨다 — create_collection과 동일한 관대 정책
#       (임베딩 서버 일시 장애에도 진행). 실제 차원 불일치는 인제스트 가드2·health(가드3)가 잡는다.
#   F7: 스왑 커밋과 status/이력 커밋 사이 크래시 시 데이터 벡터는 일관(원자 스왑)하나 이력 행이 빠질
#       수 있다(운영 계보 누락). 런별 임베딩 모델은 EvalRun.env(스펙 240)에 별도 박제돼 비교는 가능.
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


@router.post("/{cid}/reindex", response_model=CollectionOut)
async def reindex_collection(
    cid: uuid.UUID,
    body: ReindexIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> CollectionOut:
    """컬렉션 재인덱싱(스펙 312) — 임베딩 모델 교체(같은 차원 1024)와/또는 청크 크기·겹침 재청킹.
    재인덱싱 중 배타 잠금(다른 접근 409). 평가 이력은 보존(건드리지 않음)."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)
    _reject_if_reindexing(c)  # 이미 잠김이면 조기 거절(CAS로도 막지만 명확 메시지)

    # ── 변경 요청 해석 + 검증 ──
    model_change = (
        body.embedding_model_id is not None and body.embedding_model_id != c.embedding_model_id
    )
    target_model = c.embedding_model
    target_model_id = c.embedding_model_id
    if body.embedding_model_id is not None:
        m = await _embedding_model(session, body.embedding_model_id)
        if m is None:
            raise HTTPException(status_code=400, detail="임베딩 모델을 찾을 수 없습니다.")
        if m.kind != "embedding":
            raise HTTPException(
                status_code=400, detail="임베딩(kind=embedding) 모델만 쓸 수 있습니다."
            )
        if m.provider is not None:  # 같은 차원(1024)만 — probe 실측(가드1 재사용)
            probe = await _probe(
                m.provider.base_url, crypto.decrypt(m.provider.api_key), m.model_id, "embedding"
            )
            msg = _dim_mismatch(probe.dims, RAG_EMBED_DIMS)
            if msg:
                raise HTTPException(status_code=409, detail=msg)
        target_model, target_model_id = m, m.id

    rechunk = body.chunk_size is not None or body.chunk_overlap is not None
    new_size = body.chunk_size if body.chunk_size is not None else c.chunk_size
    new_overlap = body.chunk_overlap if body.chunk_overlap is not None else c.chunk_overlap
    if rechunk and c.kind != "document":
        raise HTTPException(
            status_code=400,
            detail="청크 크기·겹침 재인덱싱은 문서형 컬렉션만 가능합니다(엔티티는 1행=1청크).",
        )
    chunk_change = rechunk and (new_size != c.chunk_size or new_overlap != c.chunk_overlap)

    if not model_change and not chunk_change:
        raise HTTPException(
            status_code=400,
            detail="변경할 내용이 없습니다(모델 또는 청크 크기·겹침 중 하나는 현재와 달라야 합니다).",
        )

    # 인제스트 진행 중(parsing **또는 embedding** — 스펙 334 배경 잡, codex 334 P1)이면 거절.
    # embedding을 빼면: 배경 잡이 임베딩하는 동안 재인덱싱이 시작·완료(락 해제)된 뒤 늦은
    # _persist_chunks가 조건부 UPDATE(status != reindexing)를 통과해 옛 모델 벡터/중복 청크가
    # 스왑 밖에 커밋된다. (사전 검사~CAS 사이 미시 경합 창은 정직 경계 — 단일 프로세스 dev 도구.)
    in_flight = await session.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.collection_id == cid, Document.status.in_(("parsing", "embedding")))
    )
    if in_flight:
        raise HTTPException(
            status_code=409, detail="인제스트가 진행 중입니다 — 완료 후 다시 시도하세요."
        )

    # 재청킹인데 원본 없는 문서가 있으면 거절(no silent — 어느 문서가 못 되는지 표기).
    if chunk_change:
        docs = (
            await session.execute(
                select(Document.id, Document.filename).where(Document.collection_id == cid)
            )
        ).all()
        have = (
            set(
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
            if docs
            else set()
        )
        missing = [d.filename for d in docs if d.id not in have]
        if missing:
            shown = ", ".join(missing[:5]) + (" 외" if len(missing) > 5 else "")
            raise HTTPException(
                status_code=400,
                detail=f"원본이 저장되지 않은 문서가 있어 재청킹할 수 없습니다({shown}). 재업로드가 필요합니다.",
            )

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
@router.post("/{cid}/search", response_model=CollectionSearchOut)
async def search_collection(
    cid: uuid.UUID,
    body: CollectionSearchIn,
    session: AsyncSession = Depends(get_session),
    _principal: User | str = Depends(current_principal),
) -> CollectionSearchOut:
    """retrieval 시험 — 단일 컬렉션에 질의를 던져 상위 청크를 받는다(에이전트 채팅 불요).

    **핵심**: 인-챗 도구(`build_rag_tool`)와 **같은 코어**(`runtime.search_collections`)를 호출한다 —
    평행 구현을 새로 짜면 drift나 "엔드포인트는 초록인데 채팅은 다름"이 된다(스펙 072). 등록 직후
    같은 컬렉션에 질의를 던져 retrieval 품질을 즉석 확인하는 수단(사용자 보고 '테스트 방법이 없어' 공백).

    완전성 검사(가드): embedding 모델/provider가 불완전하면 검색 불가 → 400(graceful). 차원 drift는
    health(가드3)가 담당. api_key는 백엔드에서만 복호화하며 응답에 절대 포함하지 않는다.
    """
    from . import runtime  # 지연 임포트(런타임 의존 격리)

    # 사용은 전부 공용(스펙 172) — 로그인한 누구나 검색 가능(current_principal이 익명은 401 차단).
    # 관리(수정·삭제·인제스트)는 여전히 소유자만(assert_may_manage). 존재 404만 유지.
    gate = await _load_collection(session, cid)
    if gate is None:
        raise HTTPException(status_code=404, detail="not found")
    col = await resolve_search_collection(session, cid)
    try:
        hits = await runtime.search_collections([col], body.query, body.top_k)
    except runtime.RagSearchError as exc:
        # 무중단 재인덱싱(스펙 313): 검색은 재인덱싱에 막히지 않으므로 locked(409)는 더 이상 발생하지
        # 않는다. 빈 질의는 스키마(min_length=1)가 먼저 막으므로 여기 도달하는 건 embed/db 실패 — 502.
        raise HTTPException(status_code=502, detail=exc.tool_msg) from exc
    return CollectionSearchOut(
        query=body.query,
        top_k=body.top_k,
        results=[SearchHit(**h) for h in hits],
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


async def _content_length_guard(request: Request) -> None:
    """PUT 본문 크기 선검사(codex 331 P2) — Pydantic이 JSON을 파싱하기 *전에* Content-Length로
    거대 요청을 차단한다(파싱 후 len 검사만 있으면 이미 메모리에 올라온 뒤라 상한이 방어가 아님).
    **정직 경계**: Content-Length 없는 chunked 전송은 이 선검사를 우회한다(h11 수신 자체의 누적
    상한은 플랫폼 전역 미들웨어 몫 — 인증 필수 admin 표면이라 수용, 본검사 len(data)가 이중 그물)."""
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES + 65536:  # JSON 이스케이프 여유
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"본문이 너무 큽니다(최대 {limit_mb}MB).")


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
