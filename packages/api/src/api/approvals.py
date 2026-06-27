"""승인 큐 라우터 (007 도메인). 목록 조회·결정.

스펙 041(P5-a): resolve는 status flip에 그치지 않고 **멈춘 그래프를 재개**한다 —
approve면 위험 도구 실행 후 마무리, reject면 미실행 마무리. 재개 기전은 chat.resume_approval.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .chat import resume_approval
from .db import get_session
from .models import Agent, Approval, User
from .schemas import ApprovalOut, ResolveIn
from .serializers import approval_to_out

router = APIRouter(prefix="/approvals", tags=["approvals"])

# 위험 도구 실행 결정은 **admin만**(스펙 041 불변식 "admin만 재개"). 라우터의 dependencies=_auth는
# 인증만(쿠키 유저 OR 머신 토큰) 보장하므로, resolve에는 admin 인가를 추가로 건다 — 안 그러면 비-admin
# 멤버·머신 토큰이 approver=admin 도구를 승인·실행할 수 있다(적대 검증 발견, 스펙 031 컨벤션 준수).
_require_admin = Depends(authz.require("approvals", "resolve"))


async def _agent_id_map(session: AsyncSession) -> dict:
    rows = (await session.execute(select(Agent.id, Agent.agent_id))).all()
    return {row.id: row.agent_id for row in rows}


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ApprovalOut]:
    # pending 먼저, 그 다음 requested_at 내림차순.
    # status를 주면 그 상태만 — 사이드바 배지·승인 큐는 'pending'만 본다(045 정직화).
    # 기본(None)은 전량 반환(기존 소비처 회귀 방지).
    pending_first = case((Approval.status == "pending", 0), else_=1)
    stmt = select(Approval).order_by(pending_first, Approval.requested_at.desc())
    if status is not None:
        # 필터 분기도 pending-first 정렬 유지(스펙 §A 충실성; status='pending'이면 무영향이나
        # 다른 status 질의에도 문서화한 불변식이 깨지지 않게).
        stmt = (
            select(Approval)
            .where(Approval.status == status)
            .order_by(pending_first, Approval.requested_at.desc())
        )
    result = await session.execute(stmt)
    amap = await _agent_id_map(session)
    return [approval_to_out(p, amap.get(p.agent_pk)) for p in result.scalars().all()]


@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(
    approval_id: str,
    body: ResolveIn,
    session: AsyncSession = Depends(get_session),
    _admin: User = _require_admin,
) -> ApprovalOut:
    result = await session.execute(
        select(Approval).where(Approval.approval_id == approval_id)
    )
    p = result.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    decision = "approve" if body.decision == "approve" else "reject"
    new_status = "approved" if decision == "approve" else "rejected"
    # 이중 처리 가드(스펙 041 불변식): **원자적 조건부 UPDATE** — pending→결정으로 박되 status가
    # 이미 pending이 아니면 0행. read-then-write로 두면 동시 두 resolve가 둘 다 가드를 통과해 위험
    # 도구가 2회 실행되는 TOCTOU가 생긴다. WHERE status='pending'를 DB가 한 번에 판정해 정확히
    # 한 요청만 재개로 진입(나머지는 409). 재개는 부수효과를 동반하므로 멱등이 아니다.
    res = await session.execute(
        update(Approval)
        .where(Approval.approval_id == approval_id, Approval.status == "pending")
        .values(status=new_status)
    )
    if res.rowcount == 0:
        raise HTTPException(
            status_code=409, detail="이미 처리되었거나 처리 중인 승인입니다."
        )
    await session.commit()
    await session.refresh(p)  # commit으로 만료된 ORM 객체 재적재(재개·직렬화가 최신 값 사용)
    # status를 먼저 박은 뒤 그래프 재개 — 재개 도중 크래시해도 status는 남아 재시도가 가드에
    # 걸린다(거부 방향 안전: 미실행 유지). 재개는 자체 _load_context/체크포인터로 독립 수행.
    await resume_approval(p, decision)
    a = await session.get(Agent, p.agent_pk) if p.agent_pk else None
    return approval_to_out(p, a.agent_id if a else None)
