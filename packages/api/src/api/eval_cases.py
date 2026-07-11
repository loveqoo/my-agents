"""케이스(EvalCase) CRUD 라우트(스펙 137·178, 스펙 291 분할).

케이스는 owner가 없다 — 부모 문제집 소유로 관리 판정(비소유 404-fold).
"""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_principal
from .db import get_session
from .eval_common import _dataset_or_404, _gate_harvest_read, _validate_asserts, router
from .eval_schemas import CaseIn, CaseOut
from .models import EvalCase, EvalDataset, User
from .ownership import assert_may_manage


@router.get("/datasets/{dataset_id}/cases", response_model=list[CaseOut])
async def list_cases(
    dataset_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> list[CaseOut]:
    ds = await _dataset_or_404(session, dataset_id)
    _gate_harvest_read(ds, user)  # 수확 케이스(입력=사용자 질문)는 소유자/admin만(codex P2 F1)
    rows = (
        (
            await session.execute(
                select(EvalCase)
                .where(EvalCase.dataset_id == dataset_id)
                .order_by(EvalCase.order_idx, EvalCase.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [CaseOut.model_validate(c) for c in rows]


@router.post("/datasets/{dataset_id}/cases", response_model=CaseOut, status_code=201)
async def create_case(
    dataset_id: uuid.UUID,
    body: CaseIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> CaseOut:
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 문제집 소유자만 케이스 추가
    _validate_asserts(body.asserts)
    import secrets

    case = EvalCase(
        dataset_id=dataset_id,
        name=body.name or f"case-{secrets.token_hex(4)}",  # 스펙 195: 없으면 해시
        input=body.input,
        asserts=body.asserts,
        order_idx=body.order_idx,
    )
    session.add(case)
    await session.commit()
    return CaseOut.model_validate(case)


@router.patch("/cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID,
    body: CaseIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> CaseOut:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    ds = await session.get(
        EvalDataset, case.dataset_id
    )  # 케이스는 owner 없음 — 부모 문제집으로 판정
    if ds is None:
        raise HTTPException(status_code=404, detail="case not found")
    assert_may_manage(ds, user, not_found_detail="case not found")  # 소유자만(비소유 404-fold)
    _validate_asserts(body.asserts)
    if body.name is not None:  # 스펙 195: 미전송이면 기존 해시 이름 보존(덮어쓰기 금지)
        case.name = body.name
    case.input, case.asserts, case.order_idx = body.input, body.asserts, body.order_idx
    await session.commit()
    return CaseOut.model_validate(case)


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> None:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    ds = await session.get(EvalDataset, case.dataset_id)  # 부모 문제집으로 소유 판정
    if ds is None:
        raise HTTPException(status_code=404, detail="case not found")
    assert_may_manage(ds, user, not_found_detail="case not found")  # 소유자만(비소유 404-fold)
    await session.delete(case)
    await session.commit()
