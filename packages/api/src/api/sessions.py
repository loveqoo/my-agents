"""세션 라우터 (007 도메인). 세션 조회·메시지·종료."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Agent, Message, Session
from .schemas import MessageOut, SessionOut
from .serializers import session_to_out

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _agent_id_map(session: AsyncSession) -> dict:
    """agent pk(UUID) → 외부 agent_id(agt_...) 매핑."""
    rows = (await session.execute(select(Agent.id, Agent.agent_id))).all()
    return {row.id: row.agent_id for row in rows}


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    session: AsyncSession = Depends(get_session),
) -> list[SessionOut]:
    result = await session.execute(select(Session).order_by(Session.started_at.desc()))
    amap = await _agent_id_map(session)
    return [session_to_out(s, amap.get(s.agent_pk)) for s in result.scalars().all()]


async def _get_session_or_404(session: AsyncSession, session_id: str) -> Session:
    result = await session.execute(
        select(Session).where(Session.session_id == session_id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="not found")
    return s


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
