"""문제집(EvalDataset) CRUD 라우트(스펙 137·178, 스펙 291 분할).

읽기 공개(178 D1)·관리 소유자(비소유 404-fold). 수확 문제집은 읽기도 소유 스코프(스펙 209 §B).
"""

import uuid

from fastapi import Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_principal
from .db import get_session
from .eval_common import (
    _dataset_or_404,
    _dataset_out,
    _gate_harvest_read,
    _ilike_literal,
    _is_generating,
    router,
)
from .eval_schemas import DatasetIn, DatasetOut, DatasetPageOut
from .models import EvalCase, EvalDataset, User
from .ownership import assert_may_manage, is_privileged, owner_of


@router.get("/datasets", response_model=DatasetPageOut)
async def list_datasets(
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
    q: str | None = None,
    kind: str | None = Query(None, pattern="^(agent|rag)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> DatasetPageOut:
    """문제집 목록 — **최근 생성순**, 이름·설명 부분검색(q), kind 필터(agent|rag, 스펙 212),
    페이징(스펙 196). 읽기 전원 공개(178 D1)."""
    conds = []
    if kind:  # 스펙 212: 에이전트 평가/RAG 평가 분리(서버 필터로 페이징 정합 유지)
        conds.append(EvalDataset.kind == kind)
    if q and q.strip():
        term = f"%{_ilike_literal(q.strip())}%"
        conds.append(
            or_(
                EvalDataset.name.ilike(term, escape="\\"),
                func.coalesce(EvalDataset.description, "").ilike(term, escape="\\"),
            )
        )
    # 수확 문제집(source_agent_pk≠NULL)은 소유자/admin에게만 목록 노출(codex P2 F1 — 세션 파생 콘텐츠).
    # 일반 문제집은 공개(178 D1). 특권은 전부 봄.
    if not is_privileged(user):
        mine = owner_of(user)
        cond = EvalDataset.source_agent_pk.is_(None)
        if mine:
            cond = or_(cond, EvalDataset.owner_id == mine)
        conds.append(cond)
    where = and_(*conds) if conds else None
    count_stmt = select(func.count()).select_from(EvalDataset)
    if where is not None:
        count_stmt = count_stmt.where(where)
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = (
        select(EvalDataset, func.count(EvalCase.id))
        .outerjoin(EvalCase, EvalCase.dataset_id == EvalDataset.id)
        .group_by(EvalDataset.id)
        .order_by(EvalDataset.created_at.desc(), EvalDataset.id.desc())
    )
    if where is not None:
        stmt = stmt.where(where)
    rows = (await session.execute(stmt.offset(offset).limit(limit))).all()
    return DatasetPageOut(
        items=[_dataset_out(d, n, user) for d, n in rows],  # 관리 버튼은 소유자만(헬퍼가 계산)
        total=total,
        any_generating=any(_is_generating(d) for d, _ in rows),
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> DatasetOut:
    """문제집 단건 — 열린 드로어 rebind용(폴링 시 generating 종료·collection_id 반영, 스펙 196).
    읽기 공개(178 D1) · 없으면 404."""
    ds = await _dataset_or_404(session, dataset_id)
    _gate_harvest_read(ds, user)  # 수확 문제집은 소유자/admin만(codex P2 F1)
    n = (
        await session.execute(
            select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset_id)
        )
    ).scalar_one()
    return _dataset_out(ds, n, user)


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def create_dataset(
    body: DatasetIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> DatasetOut:
    ds = EvalDataset(
        name=body.name,
        description=body.description,
        kind=body.kind,
        owner_id=owner_of(user),
        # 스펙 193: rag 문제집만 대상 컬렉션 고정(agent는 무의미 → None으로 무시).
        collection_id=body.collection_id if body.kind == "rag" else None,
    )
    session.add(ds)
    try:
        await session.commit()
    except Exception as err:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 문제집이 이미 있습니다") from err
    return _dataset_out(ds, 0, user)


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    dataset_id: uuid.UUID,
    body: DatasetIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> DatasetOut:
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 소유자만(비소유 404-fold)
    ds.name, ds.description, ds.kind = body.name, body.description, body.kind
    await session.commit()
    n = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id))
    ).scalar_one()
    return _dataset_out(ds, n, user)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> None:
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 소유자만(비소유 404-fold)
    await session.delete(ds)  # cases·runs CASCADE
    await session.commit()
