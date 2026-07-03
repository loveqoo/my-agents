"""평가 하네스 제품화 라우터 — 문제집/케이스 CRUD + 실행/성적표 (스펙 137, admin 보호).

authz는 admin(*,*)이 ("eval",*)을 커버(batch_routes 미러 — 1탄은 admin 전용이 안전 기본값,
member 개방은 후속 논의). asserts는 선언적 JSON → `eval_harness.build_asserts`가 **닫힌 type
집합**으로 검증(미지 type=400, 조용한 통과 금지 — 평가는 fail-closed).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .db import get_session
from .eval_harness import build_asserts
from .models import EvalCase, EvalDataset
from .ownership import owner_of

router = APIRouter(prefix="/eval", tags=["eval"])

_manage = Depends(authz.require("eval", "manage"))
_run_dep = Depends(authz.require("eval", "run"))


# ----------------------------- 스키마 -----------------------------
class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    kind: str = Field(default="agent", pattern="^(agent|rag)$")


class DatasetOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    kind: str
    case_count: int = 0


class CaseIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1)
    asserts: list = Field(default_factory=list)
    order_idx: int = 0


class CaseOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    input: str
    asserts: list
    order_idx: int
    model_config = {"from_attributes": True}


def _validate_asserts(asserts: list) -> None:
    """선언 asserts를 저장 전에 검증 — build_asserts의 닫힌 집합·형식 규칙 그대로(단일 출처)."""
    try:
        build_asserts(asserts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def _dataset_or_404(session: AsyncSession, dataset_id: uuid.UUID) -> EvalDataset:
    ds = await session.get(EvalDataset, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return ds


# ----------------------------- 데이터셋 CRUD -----------------------------
@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(
    session: AsyncSession = Depends(get_session), user=_manage
) -> list[DatasetOut]:
    rows = (
        await session.execute(
            select(EvalDataset, func.count(EvalCase.id))
            .outerjoin(EvalCase, EvalCase.dataset_id == EvalDataset.id)
            .group_by(EvalDataset.id)
            .order_by(EvalDataset.name)
        )
    ).all()
    return [
        DatasetOut(id=d.id, name=d.name, description=d.description, kind=d.kind, case_count=n)
        for d, n in rows
    ]


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def create_dataset(
    body: DatasetIn, session: AsyncSession = Depends(get_session), user=_manage
) -> DatasetOut:
    ds = EvalDataset(
        name=body.name, description=body.description, kind=body.kind, owner_id=owner_of(user)
    )
    session.add(ds)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 문제집이 이미 있습니다")
    return DatasetOut(id=ds.id, name=ds.name, description=ds.description, kind=ds.kind, case_count=0)


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    dataset_id: uuid.UUID,
    body: DatasetIn,
    session: AsyncSession = Depends(get_session),
    user=_manage,
) -> DatasetOut:
    ds = await _dataset_or_404(session, dataset_id)
    ds.name, ds.description, ds.kind = body.name, body.description, body.kind
    await session.commit()
    n = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id))
    ).scalar_one()
    return DatasetOut(id=ds.id, name=ds.name, description=ds.description, kind=ds.kind, case_count=n)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=_manage
) -> None:
    ds = await _dataset_or_404(session, dataset_id)
    await session.delete(ds)  # cases·runs CASCADE
    await session.commit()


# ----------------------------- 케이스 CRUD -----------------------------
@router.get("/datasets/{dataset_id}/cases", response_model=list[CaseOut])
async def list_cases(
    dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=_manage
) -> list[CaseOut]:
    await _dataset_or_404(session, dataset_id)
    rows = (
        await session.execute(
            select(EvalCase)
            .where(EvalCase.dataset_id == dataset_id)
            .order_by(EvalCase.order_idx, EvalCase.created_at)
        )
    ).scalars().all()
    return [CaseOut.model_validate(c) for c in rows]


@router.post("/datasets/{dataset_id}/cases", response_model=CaseOut, status_code=201)
async def create_case(
    dataset_id: uuid.UUID,
    body: CaseIn,
    session: AsyncSession = Depends(get_session),
    user=_manage,
) -> CaseOut:
    await _dataset_or_404(session, dataset_id)
    _validate_asserts(body.asserts)
    case = EvalCase(
        dataset_id=dataset_id, name=body.name, input=body.input,
        asserts=body.asserts, order_idx=body.order_idx,
    )
    session.add(case)
    await session.commit()
    return CaseOut.model_validate(case)


@router.patch("/cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID, body: CaseIn, session: AsyncSession = Depends(get_session), user=_manage
) -> CaseOut:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _validate_asserts(body.asserts)
    case.name, case.input, case.asserts, case.order_idx = (
        body.name, body.input, body.asserts, body.order_idx,
    )
    await session.commit()
    return CaseOut.model_validate(case)


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=_manage
) -> None:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    await session.delete(case)
    await session.commit()
