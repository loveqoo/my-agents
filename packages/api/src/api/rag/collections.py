"""rag.collections — 라우트 핸들러(스펙 381 분할). 서비스/헬퍼는 shared."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import crypto
from ..auth import current_principal
from ..db import get_or_404, get_session
from ..model_registry import _probe
from ..models import (
    RAG_EMBED_DIMS,
    Collection,
    User,
)
from ..naming import validate_resource_name
from ..ownership import assert_may_manage, may_manage, owner_of
from ..references import agents_referencing, referenced_message
from ..schemas import (
    CollectionHealth,
    CollectionIn,
    CollectionOut,
    CollectionUpdate,
)
from ..serializers import collection_to_out
from .embedding_models import _load_collection, _validate_embedding_model
from .reindex_core import _reject_if_reindexing
from .router import router
from .schema_guards import _check_entity_schema


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
    # 임베딩 모델 검증(가드1: 존재·kind·차원) — 재인덱싱과 공유 단일 출처(스펙 375).
    await _validate_embedding_model(session, body.embedding_model_id)
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
# 조건부 UPDATE(_finalize_ingest, status!='reindexing')로 경합을 닫는다(codex F1, 스펙 432서 말미 이동).
#
# 알려진 경계(codex 적대 리뷰 — 안전 위반 아닌 미문서 경계, 개인 단일 워커 배포 전제, 스펙 312 OUT):
#   F4: update/delete_collection의 _reject_if_reindexing은 point-in-time 가드(TOCTOU 창 존재).
#       reindex-vs-reindex는 CAS로 원자 배타지만, 관리 CRUD-vs-reindex는 best-effort(드문 관리 액션).
#   F5: 대상 모델 probe 실패(None)면 차원 검증을 통과시킨다 — create_collection과 동일한 관대 정책
#       (임베딩 서버 일시 장애에도 진행). 실제 차원 불일치는 인제스트 가드2·health(가드3)가 잡는다.
#   F7: 스왑 커밋과 status/이력 커밋 사이 크래시 시 데이터 벡터는 일관(원자 스왑)하나 이력 행이 빠질
#       수 있다(운영 계보 누락). 런별 임베딩 모델은 EvalRun.env(스펙 240)에 별도 박제돼 비교는 가능.
