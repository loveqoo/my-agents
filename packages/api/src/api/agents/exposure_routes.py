"""노출 라우트 — A2A 노출 토글·공개/비공개 전환(스펙 154)."""

import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agent.runtime import is_third_party

from ..auth import current_principal
from ..db import get_session
from ..ownership import assert_may_manage, owner_of
from ..schemas import AgentOut, ExposeIn
from .helpers import _load_agent, _reload_out
from .routers import router


# ----------------------------- A2A 노출 -----------------------------
@router.put("/{agent_id}/expose", response_model=AgentOut)
async def expose_agent(
    agent_id: uuid.UUID,
    body: ExposeIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> AgentOut:
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(
        agent, principal, not_found_detail="agent not found"
    )  # 소유자/특권만(스펙 112)

    if body.a2a and agent.owner_id is not None:
        # 트리 불변식(스펙 147): private(소유자 전용) 에이전트는 A2A 공유가 성립하지 않는다 —
        # 소유자만 쓰는 걸 다른 에이전트가 호출하게 열면 사용 게이트가 뚫린다. 끄기는 항상 허용.
        raise HTTPException(
            status_code=400, detail="private 에이전트는 A2A를 켤 수 없습니다 (public만 가능)"
        )
    if body.a2a and is_third_party(agent.source):
        # 재공개 금지(스펙 152) — 외부에서 받아온 에이전트만 차단. code(제1자 SDK 배포)는 스펙 154에서
        # 1홉 중계로 노출 허용(직접 코딩 에이전트도 우리 A2A 주소로 공개). 끄기는 source 무관 항상 허용.
        raise HTTPException(
            status_code=400,
            detail="외부에서 가져온 에이전트는 A2A로 재공개할 수 없습니다",
        )
    # exposed는 JSONB(MutableDict 미추적) — 통째 교체 대신 형제 키 보존하며 a2a만 갱신 후 재대입.
    agent.exposed = {**(agent.exposed or {}), "a2a": body.a2a}
    await session.commit()
    return await _reload_out(session, agent.id)


# ----------------------------- 공개/비공개 전환 (스펙 154 — 백로그 ③ 승격) -----------------------------
class VisibilityIn(BaseModel):
    public: bool


@router.put("/{agent_id}/visibility", response_model=AgentOut)
async def set_agent_visibility(
    agent_id: uuid.UUID,
    body: VisibilityIn,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> AgentOut:
    """private↔public 전환(스펙 154). 소유자/특권만.

    - 승격(public=True): owner_id→None(147 의미론: public=모두 사용). 069의 이전 금지와 구분 —
      타인으로의 이전이 아니라 소유자 본인/특권의 명시적 **소유 해제**.
    - 강등(public=False): owner_id←요청 주체 스탬프. 이미 private면 기존 소유자 보존(no-takeover).
      **A2A가 켜져 있으면 자동 off**(private+A2A 조합 불변식, 147). 머신 토큰은 강등 불가(소유자
      없음 → 400 — no-op 거짓 성공 방지).
    - 경계(정직): 승격→강등을 거치면 원소유자 기록은 소실(마지막 강등 주체가 소유자)."""
    agent = await _load_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    assert_may_manage(agent, principal, not_found_detail="agent not found")
    if body.public:
        agent.owner_id = None
    else:
        if agent.owner_id is None:
            new_owner = owner_of(principal)
            if new_owner is None:
                raise HTTPException(
                    status_code=400,
                    detail="머신 토큰으로는 비공개 전환할 수 없습니다(소유자 없음).",
                )
            agent.owner_id = new_owner
        # 이미 private면 기존 소유자 보존(069 no-takeover)
        agent.exposed = {**(agent.exposed or {}), "a2a": False}  # private+A2A 봉인(147)
    await session.commit()
    return await _reload_out(session, agent.id)
