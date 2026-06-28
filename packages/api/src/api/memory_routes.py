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
from .auth import current_principal
from .authz import get_enforcer
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


class MemoryUserList(BaseModel):
    # 스펙 053 — 역할 기반 스코핑. 프론트가 드롭다운 노출 여부를 백엔드 판정으로 결정하게 한다
    # (Casbin admin 역할은 클라이언트가 모르므로 capability를 실어 내린다).
    can_curate_others: bool  # memory:manage 보유 — 타 유저 메모리 열람·교정 가능
    me: MemoryUserOut | None  # 현재 주체 신원(머신 토큰=null — 유저 신원 없음)
    users: list[MemoryUserOut]  # 어드민=전체 distinct, 비-어드민=[me]


def _can_curate_others(principal) -> bool:
    """타 유저 메모리 열람·교정 권한(memory:manage 등가). 머신 토큰=소유자=어드민 등가,
    is_superuser=우회(authz.py 패턴), 그 외엔 Casbin enforce(기본정책 admin '*,*'가 통과).
    기본정책이 memory:manage를 이미 커버 → 새 시드 불요. 스펙 053."""
    if principal == "machine":
        return True
    if getattr(principal, "is_superuser", False):
        return True
    return get_enforcer().enforce(str(principal.id), "memory", "manage")


def _assert_principal_may_access(principal, user_id: str) -> None:
    """principal-레벨 게이트 — 비-어드민은 자기 user_id만. mem_id가 그 user_id 소유인지 보는
    `_assert_user_owns`(row-레벨)와 **별개**, 둘 다 필요(전자=주체×대상, 후자=대상×행)."""
    if _can_curate_others(principal):
        return
    own = None if principal == "machine" else str(principal.id)
    if user_id != own:
        raise HTTPException(status_code=403, detail="다른 유저의 메모리에 접근할 수 없습니다")


def _principal_identity(principal) -> MemoryUserOut | None:
    if principal == "machine":
        return None
    return MemoryUserOut(
        user_id=str(principal.id), email=principal.email, display_name=principal.display_name
    )


@router.get("/users", response_model=MemoryUserList)
async def list_memory_users(
    principal=Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> MemoryUserList:
    """유저 메모리 큐레이션 대상 목록 — **현재 주체가 접근 허용된 범위만**(스펙 053).

    비-어드민: `users=[me]`(본인만 — 메모리가 없어도 1건 둬 빈 패널이라도 보게). 어드민/머신:
    대화에 쓰인 distinct user_id 전체에 신원(email·display_name) 보강(스펙 052, JOIN으로만).
    `can_curate_others`로 프론트가 드롭다운 노출을 결정한다. `/sessions/users`(Playground·021)와
    분리 — 그쪽은 신원·권한 스코핑 없는 list[str].
    """
    me = _principal_identity(principal)
    if not _can_curate_others(principal):
        return MemoryUserList(can_curate_others=False, me=me, users=[me] if me else [])

    rows = (
        await session.execute(
            select(SessionModel.user_id, func.max(SessionModel.last_activity).label("last"))
            .where(SessionModel.user_id.is_not(None))
            .group_by(SessionModel.user_id)
            .order_by(func.max(SessionModel.last_activity).desc())
        )
    ).all()
    uids = [r.user_id for r in rows]
    users_out: list[MemoryUserOut] = []
    if uids:
        # user_id(str) ↔ User.id(UUID) 캐스팅 회피 — distinct 수가 적어 파이썬 측 매핑이 안전·단순.
        users = (await session.execute(select(User))).scalars().all()
        by_id = {str(u.id): u for u in users}
        for uid in uids:
            u = by_id.get(uid)
            users_out.append(
                MemoryUserOut(
                    user_id=uid,
                    email=u.email if u else None,  # 미등록 user_id면 None(graceful)
                    display_name=u.display_name if u else None,
                )
            )
    return MemoryUserList(can_curate_others=True, me=me, users=users_out)


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
    user_id: str,
    principal=Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """유저(user_id) 장기 기억 목록. 메모리 미가용이면 빈 목록(graceful)."""
    _assert_principal_may_access(principal, user_id)
    mem_cfg = await _user_mem_cfg(session)
    if mem_cfg is None:
        return []
    return await asyncio.to_thread(memory.list_memories, {"user_id": user_id}, mem_cfg)


@router.patch("/user/{user_id}/{mem_id}")
async def update_user_memory(
    user_id: str,
    mem_id: str,
    body: UserMemoryIn,
    principal=Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """교정 — 유저 기억 본문 수정(본인 또는 어드민)."""
    _assert_principal_may_access(principal, user_id)
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
    user_id: str,
    mem_id: str,
    principal=Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    """교정 — 유저 기억 삭제(본인 또는 어드민)."""
    _assert_principal_may_access(principal, user_id)
    mem_cfg = await _user_mem_cfg(session)
    if mem_cfg is None:
        raise HTTPException(status_code=400, detail="장기 메모리가 활성화되지 않았습니다")
    await _assert_user_owns(user_id, mem_id, mem_cfg)
    ok = await asyncio.to_thread(memory.delete_memory, mem_id, mem_cfg)
    if not ok:
        raise HTTPException(status_code=400, detail="메모리 삭제 실패")
