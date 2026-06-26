"""세션 라우터 (007 도메인). 세션 조회·메시지·종료."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Agent, Message, Session
from .schemas import MessageOut, SessionOut, SessionPage
from .serializers import session_to_out

router = APIRouter(prefix="/sessions", tags=["sessions"])

# 버킷 → status 매핑 (단일출처 — 프론트는 버킷 문자열만 보낸다). 스펙 034.
_STATUS_BUCKETS: dict[str, tuple[str, ...]] = {
    "live": ("active", "running", "draining"),
    "awaiting": ("awaiting",),
    "error": ("error",),
}


def _bucket_of(status: str) -> str | None:
    """status 값이 속한 배지 버킷(all 제외). 미매핑 status는 None."""
    for bucket, members in _STATUS_BUCKETS.items():
        if status in members:
            return bucket
    return None


async def _agent_id_map(session: AsyncSession) -> dict:
    """agent pk(UUID) → 외부 agent_id(agt_...) 매핑."""
    rows = (await session.execute(select(Agent.id, Agent.agent_id))).all()
    return {row.id: row.agent_id for row in rows}


@router.get("", response_model=SessionPage)
async def list_sessions(
    status: str = "all",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SessionPage:
    """세션 목록 (페이징·필터·배지 집계). 스펙 034.

    - `status`: 버킷(all|live|awaiting|error). 미지정/미지의 값은 all로 폴백(관대).
    - `total`: 현재 필터 적용 총 건수. `counts`: 전체 집계(필터 무관, 배지용).
    """
    members = _STATUS_BUCKETS.get(status)

    base = select(Session)
    if members is not None:
        base = base.where(Session.status.in_(members))

    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    rows = (
        await session.execute(
            base.order_by(Session.started_at.desc(), Session.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    # 배지 카운트: 전체 GROUP BY 1회 → 버킷으로 접기 (필터 무관, 항상 정확).
    counts = {"all": 0, "live": 0, "awaiting": 0, "error": 0}
    grouped = (
        await session.execute(
            select(Session.status, func.count()).group_by(Session.status)
        )
    ).all()
    for st, n in grouped:
        counts["all"] += n
        bucket = _bucket_of(st)
        if bucket is not None:
            counts[bucket] += n

    amap = await _agent_id_map(session)
    items = [session_to_out(s, amap.get(s.agent_pk)) for s in rows]
    return SessionPage(items=items, total=total, counts=counts)


async def _get_session_or_404(session: AsyncSession, session_id: str) -> Session:
    result = await session.execute(
        select(Session).where(Session.session_id == session_id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="not found")
    return s


@router.get("/users", response_model=list[str])
async def list_user_ids(session: AsyncSession = Depends(get_session)) -> list[str]:
    """대화에 쓰인 distinct userId, 최근 사용순(스펙 021 — Playground 헤더 선택지).

    NOTE: 이 정적 경로는 아래 `/{session_id}`보다 **먼저** 선언돼야 가려지지 않는다.
    """
    rows = (
        await session.execute(
            select(Session.user_id, func.max(Session.last_activity).label("last"))
            .where(Session.user_id.is_not(None))
            .group_by(Session.user_id)
            .order_by(func.max(Session.last_activity).desc())
        )
    ).all()
    return [r.user_id for r in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session_detail(
    session_id: str,
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    s = await _get_session_or_404(session, session_id)
    a = await session.get(Agent, s.agent_pk)
    return session_to_out(s, a.agent_id if a else None)


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_session_messages(
    session_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    s = await _get_session_or_404(session, session_id)
    result = await session.execute(
        select(Message)
        .where(Message.session_pk == s.id)
        .order_by(Message.created_at)
    )
    return [
        MessageOut(role=m.role, content=m.content, trace=m.trace)
        for m in result.scalars().all()
    ]


@router.post("/{session_id}/end", response_model=SessionOut)
async def end_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    s = await _get_session_or_404(session, session_id)
    s.status = "completed"
    await session.commit()
    a = await session.get(Agent, s.agent_pk)
    return session_to_out(s, a.agent_id if a else None)
