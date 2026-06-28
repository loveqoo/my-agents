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


_PREVIEW_LEN = 80


async def _badge_counts(session: AsyncSession) -> dict:
    """배지 카운트: 전체 GROUP BY 1회 → 버킷으로 접기 (필터 무관, 항상 전역)."""
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
    return counts


async def _session_previews(session: AsyncSession, pks: list) -> dict:
    """세션 pk → 첫 사용자 메시지 일부(사람이 알아볼 라벨, 스펙 055). 페이지의 세션만 1쿼리.

    role='user' 메시지를 (session_pk, created_at) 정렬로 한 번에 받아 세션별 *최초*만 취한다.
    """
    if not pks:
        return {}
    rows = (
        await session.execute(
            select(Message.session_pk, Message.content)
            .where(Message.session_pk.in_(pks), Message.role == "user")
            .order_by(Message.session_pk, Message.created_at)
        )
    ).all()
    out: dict = {}
    for pk, content in rows:
        if pk not in out:  # 정렬상 첫 행 = 최초 사용자 메시지
            text = (content or "").strip().replace("\n", " ")
            out[pk] = text[:_PREVIEW_LEN] + ("…" if len(text) > _PREVIEW_LEN else "")
    return out


@router.get("", response_model=SessionPage)
async def list_sessions(
    status: str = "all",
    agent_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SessionPage:
    """세션 목록 (페이징·필터·배지 집계). 스펙 034 + agent 필터(스펙 055).

    - `status`: 버킷(all|live|awaiting|error). 미지정/미지의 값은 all로 폴백(관대).
    - `agent_id`: 외부 agent_id(agt_...). 주어지면 해당 에이전트 세션만(items/total). Playground
      세션 이어가기용. 미지의 id는 빈 목록(404 아님 — 목록 API 관대). `counts`는 전역 유지.
    - `total`: 현재 필터 적용 총 건수. `counts`: 전체 집계(필터 무관, 배지용).
    """
    members = _STATUS_BUCKETS.get(status)

    base = select(Session)
    if members is not None:
        base = base.where(Session.status.in_(members))
    if agent_id is not None:
        # 외부 agent_id → pk로 해석해 Session.agent_pk 필터. agent 스코프 한정(타 에이전트 누출 0).
        agent_pk = (
            await session.execute(select(Agent.id).where(Agent.agent_id == agent_id))
        ).scalar_one_or_none()
        if agent_pk is None:
            # 미지의 agent_id → 빈 목록(관대, 404 아님). `== None`은 SQL상 IS NULL이라
            # NULL agent_pk 행을 잡을 수 있으므로(스키마상 비-NULL이지만 방어적) 명시 단락한다.
            return SessionPage(items=[], total=0, counts=await _badge_counts(session))
        base = base.where(Session.agent_pk == agent_pk)

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

    counts = await _badge_counts(session)
    amap = await _agent_id_map(session)
    previews = await _session_previews(session, [s.id for s in rows])
    items = [
        session_to_out(s, amap.get(s.agent_pk), previews.get(s.id)) for s in rows
    ]
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
