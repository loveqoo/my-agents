"""승인 큐 라우터 (007 도메인). 목록 조회·결정.

스펙 041(P5-a): resolve는 status flip에 그치지 않고 **멈춘 그래프를 재개**한다 —
approve면 위험 도구 실행 후 마무리, reject면 미실행 마무리. 재개 기전은 chat.resume_approval.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .auth import current_principal
from .chat import resume_approval
from .db import get_session
from .models import Agent, Approval
from .schemas import ApprovalOut, ResolveIn
from .serializers import approval_to_out

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _is_admin(principal) -> bool:
    """principal이 전체 승인 권한(admin급)인가 — 머신 토큰 또는 superuser/`approvals:resolve` 유저."""
    if isinstance(principal, str):  # "machine" 센티넬 = owner급 전체 접근(스펙 011/031)
        return True
    if getattr(principal, "is_superuser", False):
        return True
    return authz.get_enforcer().enforce(str(principal.id), "approvals", "resolve")


def _may_resolve(approval: Approval, principal) -> bool:
    """resolve 인가 3-way(스펙 066). admin/머신=무엇이든, owner+self_approve=자기 것, 그 외 거부.

    - 머신/admin → True(전체).
    - owner(요청 주체 본인) AND 그 permission이 self_approve로 열림 → True(자기 것만).
      매칭은 *DB의* approval.user_id/permission 대 *서버가 쥔* principal로만(요청 본문 무관, T3/T6).
      user_id가 None(머신/레거시 발)이면 owner 분기 자체가 닫힌다(T2 fail-closed).
    - 그 외(민감 permission, 정책 부재) → False → 403(T7).
    """
    if _is_admin(principal):
        return True
    # 여기 도달 = 비-admin 유저. owner + self_approve 정책만 허용.
    return (
        approval.user_id is not None
        and approval.user_id == str(principal.id)
        and authz.can_self_approve(str(principal.id), approval.permission)
    )


def _own_scope(principal) -> str | None:
    """list 스코핑 키 — 일반 유저면 자기 user_id(본인 것만), admin/머신이면 None(전체)."""
    if _is_admin(principal):
        return None
    return str(principal.id)


async def _agent_id_map(session: AsyncSession) -> dict:
    rows = (await session.execute(select(Agent.id, Agent.agent_id))).all()
    return {row.id: row.agent_id for row in rows}


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> list[ApprovalOut]:
    # pending 먼저, 그 다음 requested_at 내림차순.
    # status를 주면 그 상태만 — 사이드바 배지·승인 큐는 'pending'만 본다(045 정직화).
    # 기본(None)은 전 상태 반환(기존 소비처 회귀 방지).
    # 일반 유저는 **자기 것만**(스펙 066 D5) — NULL-owner(머신/레거시)는 숨김. admin/머신은 전체.
    pending_first = case((Approval.status == "pending", 0), else_=1)
    conds = []
    if status is not None:
        conds.append(Approval.status == status)
    own = _own_scope(principal)
    if own is not None:
        conds.append(Approval.user_id == own)
    stmt = select(Approval)
    if conds:
        stmt = stmt.where(*conds)
    stmt = stmt.order_by(pending_first, Approval.requested_at.desc())
    result = await session.execute(stmt)
    amap = await _agent_id_map(session)
    return [approval_to_out(p, amap.get(p.agent_pk)) for p in result.scalars().all()]


@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(
    approval_id: str,
    body: ResolveIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> ApprovalOut:
    result = await session.execute(
        select(Approval).where(Approval.approval_id == approval_id)
    )
    p = result.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    # 열거 오라클 차단(스펙 066 적대리뷰 Low#1): 비-admin이 *볼 수 없는* 행(자기 것 아님·NULL-owner)은
    # 존재 자체를 숨긴다 → 부재(404)와 동일 응답. 안 그러면 approval_id 추측으로 404↔403을 갈라
    # 타인 승인 행의 존재를 캐낼 수 있다(목록은 이미 스코핑돼 안 보이는데 resolve가 새는 격). 단,
    # *자기* 행이지만 권한 미달(민감 perm)은 403 유지 — 이미 자기 목록에 보여 존재는 알려진 상태다.
    own = _own_scope(principal)
    if own is not None and p.user_id != own:
        raise HTTPException(status_code=404, detail="not found")
    # 인가 3-way(스펙 066): admin/머신=전체, owner+self_approve=자기 것, 그 외 403. 조회 *후* 판정 —
    # 권한 없으면 어떤 부수효과(status flip·재개)도 일어나기 전에 닫힌다.
    if not _may_resolve(p, principal):
        raise HTTPException(status_code=403, detail="이 승인을 결정할 권한이 없습니다")
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
