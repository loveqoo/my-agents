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
from sqlalchemy.ext.asyncio import AsyncSession

from . import memory
from .chat import default_mem_cfg
from .db import get_session

router = APIRouter(prefix="/memory", tags=["memory"])


class UserMemoryIn(BaseModel):
    text: str


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
