"""유저 메모리 큐레이션 라우터 (스펙 030).

유저 메모리(user_id 축)는 특정 에이전트에 묶이지 않는다 — 공유 pgvector에 user_id로
키잉되므로 기본 mem_cfg(default_mem_cfg)로 조회·교정한다. 관리자는 유저 사실을 *저작*하지
않고 *교정*만 한다 → list/update/delete만 제공(add 없음).

소유권 가드: mem0 update/delete는 전역 id로 동작하므로, path의 user_id 목록에 속하는
mem_id만 변조 허용(타 유저·타 에이전트 행 변조 차단 — 스펙 029 비판리뷰 교훈).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import memory
from .db import get_session
from .mem_config import default_mem_cfg
from .models import Session as SessionModel, User

router = APIRouter(prefix="/memory", tags=["memory"])


class UserMemoryIn(BaseModel):
    text: str


class MemoryUserOut(BaseModel):
    # 누출-안전을 *구조적*으로 — response_model이 이 세 필드만 통과시킨다(hashed_password·
    # is_superuser 등은 손수 만든 dict가 실수로 늘어나도 경계에서 잘린다). 스펙 052 비판리뷰.
    user_id: str
    email: str | None
    display_name: str | None


@router.get("/users", response_model=list[MemoryUserOut])
async def list_memory_users(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """유저 메모리 큐레이션용 — 대화에 쓰인 distinct user_id를 등록 유저 신원과 함께(최근순).

    `/sessions/users`(list[str], Playground·스펙 021)와 **분리**한다: 여기선 email·display_name을
    붙여 관리자가 "누구의 메모리인지" 식별하게 한다(raw UUID로는 불가 — 스펙 052). 신원 보강은
    **JOIN으로만** — `/admin/users`의 `users:manage` 권한을 요구하지 않아(메모리 화면은 비-슈퍼유저
    관리자에게도 열림) 메모리 큐레이션이 유저-관리 권한에 결합되지 않는다.
    """
    rows = (
        await session.execute(
            select(SessionModel.user_id, func.max(SessionModel.last_activity).label("last"))
            .where(SessionModel.user_id.is_not(None))
            .group_by(SessionModel.user_id)
            .order_by(func.max(SessionModel.last_activity).desc())
        )
    ).all()
    uids = [r.user_id for r in rows]
    if not uids:
        return []
    # user_id(str) ↔ User.id(UUID) 캐스팅 회피 — distinct 수가 적어 파이썬 측 매핑이 안전·단순.
    users = (await session.execute(select(User))).scalars().all()
    by_id = {str(u.id): u for u in users}
    out = []
    for uid in uids:
        u = by_id.get(uid)
        out.append(
            {
                "user_id": uid,
                "email": u.email if u else None,  # 미등록 user_id면 None(graceful)
                "display_name": u.display_name if u else None,
            }
        )
    return out


async def _user_mem_cfg(session: AsyncSession):
    """유저 메모리용 mem_cfg(기본 chat+embedding). 메모리 미가용이면 None."""
    return await default_mem_cfg(session)


async def _assert_user_owns(user_id: str, mem_id: str, mem_cfg) -> None:
    """mem_id가 이 user_id의 기억에 속하는지 확인. 공유 pgvector라 path user_id로
    소유권을 강제하지 않으면 임의 user_id/agent_id 행을 id만으로 변조 가능."""
    rows = await asyncio.to_thread(memory.list_memories, {"user_id": user_id}, mem_cfg)
    if not any(r["id"] == mem_id for r in rows):
        raise HTTPException(status_code=404, detail="이 유저의 기억이 아닙니다")


@router.get("/user/{user_id}")
async def list_user_memory(
    user_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """유저(user_id) 장기 기억 목록. 메모리 미가용이면 빈 목록(graceful)."""
    mem_cfg = await _user_mem_cfg(session)
    if mem_cfg is None:
        return []
    return await asyncio.to_thread(memory.list_memories, {"user_id": user_id}, mem_cfg)


@router.patch("/user/{user_id}/{mem_id}")
async def update_user_memory(
    user_id: str,
    mem_id: str,
    body: UserMemoryIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """관리자 교정 — 유저 기억 본문 수정."""
    text = body.text.strip()
    if not text:
        # 빈 본문으로의 교정은 내용을 소리없이 파괴한다 — 삭제는 별도 경로로. (029 비판리뷰 LOW)
        raise HTTPException(status_code=400, detail="빈 메모리는 저장할 수 없습니다")
    mem_cfg = await _user_mem_cfg(session)
    if mem_cfg is None:
        raise HTTPException(status_code=400, detail="장기 메모리가 활성화되지 않았습니다")
    await _assert_user_owns(user_id, mem_id, mem_cfg)
    ok = await asyncio.to_thread(memory.update_memory, mem_id, text, mem_cfg)
    if not ok:
        raise HTTPException(status_code=400, detail="메모리 수정 실패")
    return {"ok": True}


@router.delete("/user/{user_id}/{mem_id}", status_code=204)
async def delete_user_memory(
    user_id: str, mem_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    """관리자 교정 — 유저 기억 삭제."""
    mem_cfg = await _user_mem_cfg(session)
    if mem_cfg is None:
        raise HTTPException(status_code=400, detail="장기 메모리가 활성화되지 않았습니다")
    await _assert_user_owns(user_id, mem_id, mem_cfg)
    ok = await asyncio.to_thread(memory.delete_memory, mem_id, mem_cfg)
    if not ok:
        raise HTTPException(status_code=400, detail="메모리 삭제 실패")
