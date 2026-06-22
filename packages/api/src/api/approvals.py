"""승인 큐 라우터 (007 도메인). 목록 조회·결정."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Agent, Approval
from .schemas import ApprovalOut, ResolveIn
from .serializers import approval_to_out

router = APIRouter(prefix="/approvals", tags=["approvals"])


async def _agent_id_map(session: AsyncSession) -> dict:
    rows = (await session.execute(select(Agent.id, Agent.agent_id))).all()
    return {row.id: row.agent_id for row in rows}


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    session: AsyncSession = Depends(get_session),
) -> list[ApprovalOut]:
    # pending 먼저, 그 다음 requested_at 내림차순.
    pending_first = case((Approval.status == "pending", 0), else_=1)
    result = await session.execute(
        select(Approval).order_by(pending_first, Approval.requested_at.desc())
    )
    amap = await _agent_id_map(session)
    return [approval_to_out(p, amap.get(p.agent_pk)) for p in result.scalars().all()]


@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(
    approval_id: str,
    body: ResolveIn,
    session: AsyncSession = Depends(get_session),
) -> ApprovalOut:
    result = await session.execute(
        select(Approval).where(Approval.approval_id == approval_id)
    )
    p = result.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    p.status = "approved" if body.decision == "approve" else "rejected"
    await session.commit()
    a = await session.get(Agent, p.agent_pk) if p.agent_pk else None
    return approval_to_out(p, a.agent_id if a else None)
