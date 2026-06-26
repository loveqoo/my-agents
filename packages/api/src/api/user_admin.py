"""관리자 전용 유저·역할 관리 (스펙 031).

공개 등록은 막혀 있다(register_router 미마운트). 유저 생성은 여기 admin 엔드포인트로만 —
`authz.require("users", "manage")`로 보호한다. role 부여/회수는 Casbin grouping policy를 갱신한다.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi_users.exceptions import UserAlreadyExists
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .db import get_session
from .models import Role, User
from .schemas import AdminUserOut, RoleAssignIn, RoleOut, UserCreate
from .users import UserManager, get_user_manager

router = APIRouter(prefix="/admin", tags=["admin"])

_manage = Depends(authz.require("users", "manage"))


async def _to_out(u: User) -> AdminUserOut:
    roles = await authz.get_roles(str(u.id))
    return AdminUserOut(
        id=u.id,
        email=u.email,
        is_active=u.is_active,
        is_superuser=u.is_superuser,
        is_verified=u.is_verified,
        source=u.source,
        display_name=u.display_name,
        roles=roles,
    )


@router.get("/users", dependencies=[_manage], response_model=list[AdminUserOut])
async def list_users(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    return [await _to_out(u) for u in rows]


@router.post("/users", dependencies=[_manage], response_model=AdminUserOut, status_code=201)
async def create_user(
    body: UserCreate,
    user_manager: UserManager = Depends(get_user_manager),
):
    try:
        # safe=False: 관리자는 is_superuser/is_verified를 지정할 수 있다.
        user = await user_manager.create(body, safe=False)
    except UserAlreadyExists:
        raise HTTPException(status_code=409, detail="이미 존재하는 이메일입니다")
    return await _to_out(user)


@router.patch("/users/{user_id}/active", dependencies=[_manage], response_model=AdminUserOut)
async def set_active(
    user_id: uuid.UUID,
    active: bool,
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다")
    user.is_active = active
    await session.commit()
    await session.refresh(user)
    return await _to_out(user)


@router.get("/roles", dependencies=[_manage], response_model=list[RoleOut])
async def list_roles(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Role).order_by(Role.name))).scalars().all()
    return list(rows)


@router.post("/users/{user_id}/roles", dependencies=[_manage], response_model=AdminUserOut)
async def grant_role(
    user_id: uuid.UUID,
    body: RoleAssignIn,
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다")
    await authz.assign_role(str(user_id), body.role)
    return await _to_out(user)


@router.delete("/users/{user_id}/roles/{role}", dependencies=[_manage], response_model=AdminUserOut)
async def revoke_role(
    user_id: uuid.UUID,
    role: str,
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다")
    await authz.remove_role(str(user_id), role)
    return await _to_out(user)
