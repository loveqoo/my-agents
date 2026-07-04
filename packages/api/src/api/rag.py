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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto, rag_ingest
from .auth import current_principal
from .db import get_session
from .naming import validate_resource_name
from .ownership import assert_may_manage, may_manage, owner_of
from .model_registry import _probe
from .models import RAG_EMBED_DIMS, Chunk, Collection, Document, ModelConfig
from .references import agents_referencing, referenced_message
from .schemas import (
    CollectionHealth,
    CollectionIn,
    CollectionOut,
    CollectionSearchIn,
    CollectionSearchOut,
    CollectionUpdate,
    DocumentOut,
    DocumentPageOut,
    SearchHit,
)
from .serializers import collection_to_out
from .sessions import _like_escape

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
        for v in node:
            found = _has_banned_key(v)
            if found:
                return found
    return None


def _check_entity_schema(schema: dict | None, kind: str) -> None:
    """entity_schema 입력 검증(스펙 149) — 스키마 자체가 유효한 JSON Schema인지 등록 시점에 확인
    (업로드 때 처음 터지면 원인 추적이 어렵다). 문서형에 스키마를 주면 400(의미 없음)."""
    if schema is None:
        return
    if kind != "entity":
        raise HTTPException(status_code=400, detail="entity_schema는 엔티티 컬렉션에만 설정할 수 있습니다.")
    import json

    import jsonschema

    if len(json.dumps(schema)) > _SCHEMA_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"JSON Schema가 너무 큽니다(최대 {_SCHEMA_MAX_CHARS}자).")
    banned = _has_banned_key(schema)
    if banned:
        raise HTTPException(
            status_code=400,
            detail=f"JSON Schema의 '{banned}' 키워드는 지원하지 않습니다(정규식 제약은 v1 미지원 — 검증 비용 경계).",
        )
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise HTTPException(status_code=400, detail=f"JSON Schema가 유효하지 않습니다: {exc.message[:200]}")

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
    principal=Depends(current_principal),
) -> list[CollectionOut]:
    rows = (
        await session.execute(
            select(Collection)
            .options(selectinload(Collection.embedding_model))
            .order_by(Collection.name)
        )
    ).scalars().all()
    outs = [collection_to_out(c) for c in rows]
    for o in outs:  # 스펙 114 — 관리 가능 여부 파생
        o.can_manage = may_manage(o.owner_id, principal)
    return outs


@router.post("", response_model=CollectionOut, status_code=201)
async def create_collection(
    body: CollectionIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> CollectionOut:
    err = validate_resource_name(body.name)  # 식별 이름 규칙(스펙 148)
    if err:
        raise HTTPException(status_code=400, detail=err)
    _check_entity_schema(body.entity_schema, body.kind)  # 스키마 자체 유효성(스펙 149)
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
        alias=(body.alias or "").strip() or None,  # 별명(자유 표기, 스펙 148)
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
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 컬렉션이 이미 있습니다.")
    return collection_to_out(await _load_collection(session, c.id))


@router.get("/{cid}", response_model=CollectionOut)
async def get_collection(
    cid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
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
    principal=Depends(current_principal),
) -> CollectionOut:
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)
    # 임베딩 모델·dims·kind는 불변. 설명·청킹 설정·별명·엔티티 스키마만 갱신.
    if body.alias is not None:
        c.alias = body.alias.strip() or None  # ""=별명 비우기(스펙 148)
    if "entity_schema" in body.model_fields_set:
        # 명시적 null=스키마 제거(codex 149 — 오등록 스키마를 API로 해제 못 하면 업로드가 영구 잠김),
        # 미포함=미변경. 이후 업로드부터 적용(기존 행 재검증 없음 — 스펙 149). 문서형엔 400.
        if c.kind != "entity":
            raise HTTPException(status_code=400, detail="entity_schema는 엔티티 컬렉션에만 설정할 수 있습니다.")
        _check_entity_schema(body.entity_schema, "entity")
        c.entity_schema = body.entity_schema
    if body.description is not None:
        c.description = body.description
    if body.chunk_size is not None:
        c.chunk_size = body.chunk_size
    if body.chunk_overlap is not None:
        c.chunk_overlap = body.chunk_overlap
    await session.commit()
    return collection_to_out(await _load_collection(session, c.id))


@router.delete("/{cid}", status_code=204)
async def delete_collection(
    cid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> None:
    c = await session.get(Collection, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)
    # 참조 무결성(스펙 093): 이 컬렉션 name을 vectorTables에 담은 에이전트가 있으면 삭제 차단.
    # 삭제하면 config에 dangling name만 남아 런타임이 조용히 RAG 없이 동작(chat.py 미해석).
    refs = await agents_referencing(session, "vectorTables", c.name)
    if refs:
        raise HTTPException(
            status_code=409, detail=referenced_message(refs, "RAG 컬렉션")
        )
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


# ----------------------------- retrieval 시험(스펙 072) -----------------------------
@router.post("/{cid}/search", response_model=CollectionSearchOut)
async def search_collection(
    cid: uuid.UUID,
    body: CollectionSearchIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
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
        # 빈 질의는 스키마(min_length=1)가 먼저 막으므로 여기는 embed/db 실패만 — 502로 표면화.
        raise HTTPException(status_code=502, detail=exc.tool_msg) from exc
    return CollectionSearchOut(
        query=body.query,
        top_k=body.top_k,
        results=[SearchHit(**h) for h in hits],
    )


async def resolve_search_collection(session, cid) -> dict:
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
    principal=Depends(current_principal),
) -> Any:
    """문서 페이지 목록(스펙 128) — 문서는 증가 축이라 서버 페이지네이션 + 파일명 부분일치(q).

    세션(list_sessions)과 동형: LIMIT/OFFSET + count total + ilike(`_like_escape` 재사용 — 단일 출처).
    스코프(collection_id)는 SQL WHERE. 사용은 전부 공용(스펙 172) — 로그인한 누구나 문서 목록 조회
    가능(익명은 current_principal이 401). 존재 404만 유지(관리는 여전히 소유자만)."""
    col = await session.get(Collection, cid)
    if col is None:
        raise HTTPException(status_code=404, detail="not found")
    base = select(Document).where(Document.collection_id == cid)
    if q and q.strip():
        base = base.where(Document.filename.ilike(f"%{_like_escape(q.strip())}%", escape="\\"))
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        # id tiebreak — 같은 created_at(한 트랜잭션 일괄 인제스트)에서도 페이지가 결정적·비중복(127 원칙).
        await session.execute(base.order_by(Document.created_at, Document.id).offset(offset).limit(limit))
    ).scalars().all()
    return DocumentPageOut(items=rows, total=total)


@router.post("/{cid}/documents", response_model=DocumentOut, status_code=201)
async def ingest_document(
    cid: uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> DocumentOut:
    """업로드 → 파싱 → 청킹 → 임베딩 → pgvector 적재(동기). 실패는 status=error로 보존."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    assert_may_manage(c, principal)  # 소유자/특권만(스펙 112)

    # 적재 전 크기 차단(OOM 방지). size 헤더가 있으면 read 전에, 없으면 read 후 이중 점검.
    limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {limit_mb}MB).")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {limit_mb}MB).")

    # 엔티티 컬렉션(스펙 149): Document 영속화 **전에** 행 전수 파싱·검증 — 형식 위반은 error 문서를
    # 남기지 않고 400으로 즉시 거부(fail-closed: 소스=SQL 추출물, 위반=파이프라인 버그. 부분 스킵은
    # 비즈니스 데이터의 조용한 유실). 행 번호가 detail에 담긴다.
    entity_rows: list[tuple[str, dict]] | None = None
    if c.kind == "entity":
        try:
            entity_rows = rag_ingest.parse_entity_lines(data, schema=c.entity_schema)
        except rag_ingest.EntityParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

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
        for i, (t, v, m) in enumerate(zip(chunks, vectors, metas)):
            session.add(
                Chunk(
                    document_id=doc.id,
                    collection_id=c.id,
                    ordinal=i,
                    text=t,
                    meta=m,  # 엔티티 metadata(스펙 149) — 문서형은 None
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
    cid: uuid.UUID,
    doc_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> None:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.collection_id != cid:
        raise HTTPException(status_code=404, detail="not found")
    col = await session.get(Collection, cid)
    assert_may_manage(col, principal)  # 컬렉션 소유자/특권만(스펙 112)
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
