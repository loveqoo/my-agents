"""승인 큐 라우터 (007 도메인). 목록 조회·결정.

스펙 041(P5-a): resolve는 status flip에 그치지 않고 **멈춘 그래프를 재개**한다 —
approve면 위험 도구 실행 후 마무리, reject면 미실행 마무리. 재개 기전은 chat.resume_approval.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .auth import current_principal
from .chat import resume_approval
from .db import get_session
from .models import Agent, Approval, User
from .schemas import ApprovalOut, ApprovalPage, ResolveIn
from .serializers import approval_to_out

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _is_admin(principal: User | str) -> bool:
    """principal이 전체 승인 권한(admin급)인가 — 머신 토큰 또는 superuser/`approvals:resolve` 유저."""
    if isinstance(principal, str):  # "machine" 센티넬 = owner급 전체 접근(스펙 011/031)
        return True
    if getattr(principal, "is_superuser", False):
        return True
    return authz.get_enforcer().enforce(str(principal.id), "approvals", "resolve")


def _may_resolve(approval: Approval, principal: Any) -> bool:  # User | "machine" 센티널 duck-typing
    """resolve 인가(스펙 066 + 177 P2). admin/머신=무엇이든, 그 외는 승인자 정책에 따라.

    - 머신/admin → True(전체).
    - **approver 스탬프 有(스펙 177 P2, MCP 도구 승인)**: 진실원은 도구 정책이 박은 `approval.approver`.
        · "self" → owner(요청 주체 본인)면 True(자기 것만), 아니면 False.
        · "admin" → False(비-admin은 거부, admin 분기서 이미 처리).
      인가를 approver *필드*로 판정하므로 permission 문자열 매칭 불필요 → 세그먼트 이스케이프 무관.
    - **approver 스탬프 無(None — 레거시·메모리·A2A)**: 기존 Casbin `can_self_approve` 폴백(무회귀).
        owner AND 그 permission이 self_approve로 열림 → True. member `memory.write` 등 기존 동작 보존.
    - 어느 경우든 owner 대조는 *DB의* approval.user_id 대 *서버가 쥔* principal로만(요청 본문 무관,
      T3/T6). user_id가 None(머신/레거시 발)이면 owner 분기가 닫힌다(T2 fail-closed).
    """
    if _is_admin(principal):
        return True
    # 여기 도달 = 비-admin 유저. owner 대조는 공통 전제.
    is_owner = approval.user_id is not None and approval.user_id == str(principal.id)
    approver = getattr(approval, "approver", None)  # pre-migration/스텁 객체 방어 → None=폴백
    if approver is not None:  # 스펙 177 P2 — 도구 정책이 박은 승인자로 판정(Casbin 우회).
        return is_owner and approver == "self"
    # approver 미스탬프(레거시·메모리·A2A) → Casbin self_approve 폴백(무회귀).
    return is_owner and authz.can_self_approve(str(principal.id), approval.permission)


def _own_scope(principal: Any) -> str | None:  # User | "machine" 센티널 duck-typing
    """list 스코핑 키 — 일반 유저면 자기 user_id(본인 것만), admin/머신이면 None(전체)."""
    if _is_admin(principal):
        return None
    return str(principal.id)


async def _agent_id_map(session: AsyncSession) -> dict:
    rows = (await session.execute(select(Agent.id, Agent.agent_id))).all()
    return {row.id: row.agent_id for row in rows}


@router.get("/page", response_model=ApprovalPage)
async def list_approvals_page(
    status: str = Query("pending", pattern="^(pending|resolved)$"),
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> ApprovalPage:
    """승인 페이지 목록(스펙 251) — 무페이지네이션 전건 렌더(복잡도 1위)의 서버측 처방.

    - status=pending: 대기 큐(요청 내림차순). resolved: 처리 내역(처리 시각 내림차순).
    - q: 요약·권한·액션 부분일치(ILIKE).
    - 소유 스코프는 기존 목록과 동일(일반 유저=자기 것만, 066 D5).
    - 기존 GET /approvals(전건)는 배지 등 소비처 무회귀를 위해 유지.
    """
    conds = []
    if status == "pending":
        conds.append(Approval.status == "pending")
        order = [Approval.requested_at.desc(), Approval.id.desc()]
    else:
        conds.append(Approval.status != "pending")
        order = [Approval.resolved_at.desc().nulls_last(), Approval.id.desc()]
    if q.strip():
        needle = f"%{q.strip()}%"
        conds.append(
            or_(
                Approval.summary.ilike(needle),
                Approval.permission.ilike(needle),
                Approval.action.ilike(needle),
            )
        )
    own = _own_scope(principal)
    if own is not None:
        conds.append(Approval.user_id == own)
    total = (
        await session.execute(select(func.count()).select_from(Approval).where(*conds))
    ).scalar_one()
    stmt = select(Approval).where(*conds).order_by(*order).limit(limit).offset(offset)
    result = await session.execute(stmt)
    amap = await _agent_id_map(session)
    items = [approval_to_out(p, amap.get(p.agent_pk)) for p in result.scalars().all()]
    return ApprovalPage(items=items, total=total)


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
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
    principal: Any = Depends(
        current_principal
    ),  # User | "machine" — resolved_by 스탬프가 .id를 직접 참조
) -> ApprovalOut:
    result = await session.execute(select(Approval).where(Approval.approval_id == approval_id))
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
        # 처리 감사(스펙 181) — status와 같은 원자 UPDATE에 처리 시각·처리자를 함께 박는다
        # (별도 write 입구 안 늘림). resolved_by가 user_id(요청자)와 같으면 본인 승인.
        # 머신 토큰(str principal)은 .id가 없어 500이었다(스펙 292 타입 주석 작업이 적발) —
        # 센티널 "machine"으로 스탬프(유저 UUID와 충돌 없음, 감사 정보 보존).
        .values(
            status=new_status,
            resolved_at=func.now(),
            resolved_by="machine" if isinstance(principal, str) else str(principal.id),
        )
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=409, detail="이미 처리되었거나 처리 중인 승인입니다.")
    await session.commit()
    await session.refresh(p)  # commit으로 만료된 ORM 객체 재적재(재개·직렬화가 최신 값 사용)
    # status를 먼저 박은 뒤 그래프 재개 — 재개 도중 크래시해도 status는 남아 재시도가 가드에
    # 걸린다(거부 방향 안전: 미실행 유지). 재개는 자체 _load_context/체크포인터로 독립 수행.
    await resume_approval(p, decision)
    a = await session.get(Agent, p.agent_pk) if p.agent_pk else None
    return approval_to_out(p, a.agent_id if a else None)
