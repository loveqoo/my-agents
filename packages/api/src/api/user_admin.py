"""관리자 전용 유저·역할 관리 (스펙 031).

공개 등록은 막혀 있다(register_router 미마운트). 유저 생성은 여기 admin 엔드포인트로만 —
`authz.require("users", "manage")`로 보호한다. role 부여/회수는 Casbin grouping policy를 갱신한다.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi_users.exceptions import UserAlreadyExists
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .db import get_session
from .models import Role, User
from .schemas import AdminUserOut, PolicyIn, PolicyOut, RoleAssignIn, RoleOut, UserCreate
from .users import UserManager, get_user_manager

router = APIRouter(prefix="/admin", tags=["admin"])

_manage = Depends(authz.require("users", "manage"))
log = logging.getLogger("api.user_admin")


def _assert_grantable(obj: str, act: str) -> None:
    """능력 부여 UI 보안 경계(스펙 177 P3) — 이 표면으로 임의 리소스 권한·(*,*) 상승을 막는다.
    obj는 `capability:{kind}[:{name}]`만, 와일드카드 불가, act는 invoke 고정. 위반=400."""
    if not obj.startswith("capability:"):
        raise HTTPException(status_code=400, detail="능력 부여는 capability:* 객체만 가능합니다.")
    if "*" in obj:
        raise HTTPException(status_code=400, detail="와일드카드(*) 능력은 부여/회수할 수 없습니다.")
    if act != "invoke":
        raise HTTPException(status_code=400, detail="능력 action은 invoke만 가능합니다.")


async def _assert_valid_subject(subject: str, session: AsyncSession) -> None:
    """subject = 알려진 역할명 또는 실존 유저 UUID. 오타 grant(허공 대상)를 막는다."""
    roles = {r.name for r in (await session.execute(select(Role))).scalars()}
    if subject in roles:
        return
    try:
        uid = uuid.UUID(subject)
    except ValueError as err:
        raise HTTPException(
            status_code=400, detail="subject는 역할명 또는 유저 id여야 합니다."
        ) from err
    if await session.get(User, uid) is None:
        raise HTTPException(status_code=404, detail="대상 유저를 찾을 수 없습니다.")


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
async def list_users(session: AsyncSession = Depends(get_session)) -> list[AdminUserOut]:
    rows = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    return [await _to_out(u) for u in rows]


@router.post("/users", dependencies=[_manage], response_model=AdminUserOut, status_code=201)
async def create_user(
    body: UserCreate,
    user_manager: UserManager = Depends(get_user_manager),
) -> AdminUserOut:
    try:
        # safe=False: 관리자는 is_superuser/is_verified를 지정할 수 있다.
        user = await user_manager.create(body, safe=False)
    except UserAlreadyExists as err:
        raise HTTPException(status_code=409, detail="이미 존재하는 이메일입니다") from err
    return await _to_out(user)


@router.patch("/users/{user_id}/active", dependencies=[_manage], response_model=AdminUserOut)
async def set_active(
    user_id: uuid.UUID,
    active: bool,
    session: AsyncSession = Depends(get_session),
) -> AdminUserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다")
    user.is_active = active
    await session.commit()
    await session.refresh(user)
    return await _to_out(user)


@router.get("/roles", dependencies=[_manage], response_model=list[RoleOut])
async def list_roles(session: AsyncSession = Depends(get_session)) -> list[Role]:
    rows = (await session.execute(select(Role).order_by(Role.name))).scalars().all()
    return list(rows)


@router.post("/users/{user_id}/roles", dependencies=[_manage], response_model=AdminUserOut)
async def grant_role(
    user_id: uuid.UUID,
    body: RoleAssignIn,
    session: AsyncSession = Depends(get_session),
) -> AdminUserOut:
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
) -> AdminUserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다")
    await authz.remove_role(str(user_id), role)
    return await _to_out(user)


# ----------------------------- 능력 부여(정책) 스펙 177 P3 -----------------------------
# "누가 쓰나(역할)" 축 — 능력(capability:*)을 역할/유저에 연다. 없으면 member는 deny-by-default라
# 능력을 영영 못 쓴다. require("users","manage")로 admin 전용 + capability: 경계로 상승 차단.
@router.get("/policies", dependencies=[_manage], response_model=list[PolicyOut])
async def list_policies() -> list[PolicyOut]:
    """현재 p-정책 전량(투명성). system(기본) 정책도 포함하되, 회수는 capability:만 허용(아래)."""
    return [PolicyOut(subject=s, object=o, action=a) for s, o, a in authz.get_policies()]


@router.post("/policies", dependencies=[_manage], response_model=PolicyOut, status_code=201)
async def grant_policy(
    body: PolicyIn,
    session: AsyncSession = Depends(get_session),
    principal: User = Depends(authz.current_active_user),
) -> PolicyOut:
    _assert_grantable(body.object, body.action)  # 보안 경계
    await _assert_valid_subject(body.subject, session)
    added = await authz.add_policy(body.subject, body.object, body.action)
    log.info(
        "audit capability-grant(스펙 177 P3): admin=%s → %s %s %s (신규=%s)",
        principal.email,
        body.subject,
        body.object,
        body.action,
        added,
    )
    return PolicyOut(subject=body.subject, object=body.object, action=body.action)


@router.delete("/policies", dependencies=[_manage], status_code=204)
async def revoke_policy(
    subject: str,
    object: str,
    action: str = "invoke",
    principal: User = Depends(authz.current_active_user),
) -> None:
    _assert_grantable(object, action)  # 경계: system 정책(admin *,* 등)은 이 UI로 못 지운다
    removed = await authz.remove_policy(subject, object, action)
    log.info(
        "audit capability-revoke(스펙 177 P3): admin=%s → %s %s %s (제거=%s)",
        principal.email,
        subject,
        object,
        action,
        removed,
    )
