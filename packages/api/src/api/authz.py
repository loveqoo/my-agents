"""인가(권한) — Casbin RBAC, 정책은 우리 Postgres(casbin_rule)에 산다.

오픈/확장형 권한(스펙 031): `rbac_model.conf`로 정책을 코드에서 분리한다. 호출부는 항상
`enforce(sub, obj, act)`이고, RBAC→ABAC/도메인-RBAC로 키워도 모델 파일만 바꾼다(호출부 불변).
role 할당의 진실 원천은 casbin_rule(grouping policy `g`)이며 `roles` 테이블은 UI 카탈로그일 뿐이다.

`is_superuser`는 enforce를 우회한다(부트스트랩·운영 안전판). 그 외 민감 라우트는
`Depends(require(obj, act))`로 보호한다.

지배 스펙: docs/spec/031-multi-user-auth-and-pluggable-providers.md
"""

import logging
from pathlib import Path

import casbin
from casbin_async_sqlalchemy_adapter import Adapter
from fastapi import Depends, HTTPException

from .db import engine
from .models import User
from .users import current_active_user

log = logging.getLogger("api.authz")

_MODEL_PATH = str(Path(__file__).resolve().parent / "rbac_model.conf")

# 기본 정책(멱등 시드): admin은 전 리소스·전 행위 허용. member는 별도 정책 없이 '인증된 유저'로만
# 동작하고, 민감 라우트가 admin을 요구한다. 나중에 member에 fine-grained 정책을 정책으로 추가.
_DEFAULT_POLICIES = [
    ("admin", "*", "*"),
    # 스펙 105: 브로커 memory write는 소유자 *자기* 기억에 쓰므로 소유자 self-승인이 옳은 민감도 등급
    # (admin이 남의 개인 기억 쓰기를 승인하는 건 부적절). member가 자기 memory.write 승인을 직접 결정
    # (066 self_approve). 자기 스코프 쓰기라 self-승인이 교차유저 누출을 열지 않는다(051은 agent_id 축).
    # data.delete 등 민감 perm은 여전히 admin 전용(시드 없음 → fail-closed) — 민감도 구분 유지.
    ("member", "memory.write", "self_approve"),
]

_enforcer: casbin.AsyncEnforcer | None = None


async def init_authz() -> None:
    """부팅 시 1회 — casbin_rule 생성 + enforcer 로드 + 기본 정책 시드(멱등)."""
    global _enforcer
    adapter = Adapter(engine)
    await adapter.create_table()  # casbin_rule (없으면 생성)
    enforcer = casbin.AsyncEnforcer(_MODEL_PATH, adapter)
    await enforcer.load_policy()
    for sub, obj, act in _DEFAULT_POLICIES:
        if not enforcer.has_policy(sub, obj, act):
            await enforcer.add_policy(sub, obj, act)
    _enforcer = enforcer
    await _seed_role_catalog()
    log.info("Casbin 인가 초기화 완료 (정책 %d개)", len(enforcer.get_policy()))


# UI 표시용 role 카탈로그(할당 저장소 아님 — 진실 원천은 casbin_rule).
_ROLE_CATALOG = [
    ("admin", "전체 관리 권한(모든 리소스·행위)"),
    ("member", "기본 사용자(민감 작업 제외)"),
]


async def _seed_role_catalog() -> None:
    from sqlalchemy import select

    from .db import SessionLocal
    from .models import Role

    async with SessionLocal() as session:
        existing = set(
            (await session.execute(select(Role.name))).scalars().all()
        )
        added = False
        for name, desc in _ROLE_CATALOG:
            if name not in existing:
                session.add(Role(name=name, description=desc))
                added = True
        if added:
            await session.commit()


def get_enforcer() -> casbin.AsyncEnforcer:
    if _enforcer is None:
        raise RuntimeError("authz 미초기화 — init_authz()를 부팅 시 호출해야 한다")
    return _enforcer


# ----------------------------- role 관리 -----------------------------
async def assign_role(user_sub: str, role: str) -> None:
    """user_sub에게 role 부여(멱등). grouping policy `g, user_sub, role` 추가."""
    e = get_enforcer()
    if not e.has_grouping_policy(user_sub, role):
        await e.add_grouping_policy(user_sub, role)


async def remove_role(user_sub: str, role: str) -> None:
    e = get_enforcer()
    if e.has_grouping_policy(user_sub, role):
        await e.remove_grouping_policy(user_sub, role)


async def get_roles(user_sub: str) -> list[str]:
    return await get_enforcer().get_roles_for_user(user_sub)


# ----------------------------- self-승인 인가 (스펙 066) -----------------------------
def can_self_approve(user_sub: str, permission: str) -> bool:
    """owner가 *자기* 승인 행을 직접 결정할 수 있는가 — 그 permission이 self_approve로 열린 경우만.

    승인 권한을 action의 민감도(=permission)로 가른다(스펙 066). 정책은 `(role, permission,
    "self_approve")`로 *명시적으로 열어야* 한다 — 기본 시드엔 하나도 없어(_DEFAULT_POLICIES) 전부
    fail-closed = admin 필수. permission이 빈값/미등록이면 enforce 매칭 불가 → False(알 수 없는
    권한은 self-승인 불가, 위협 T6). superuser 우회는 여기 없음 — owner 분기는 비-admin 전용이고
    admin은 resolve의 admin 분기에서 이미 처리된다.
    """
    if not permission:
        return False
    return get_enforcer().enforce(user_sub, permission, "self_approve")


# ----------------------------- 의존성 팩토리 -----------------------------
def require(obj: str, act: str = "*"):
    """라우트 보호용 의존성 — 현재 유저가 (obj, act)를 enforce 통과해야 한다.

    superuser는 우회(부트스트랩 안전판). 실패 시 403. 세션 쿠키 미인증은 fastapi-users가 401.
    """

    async def _dep(user: User = Depends(current_active_user)) -> User:
        if user.is_superuser:
            return user
        if not get_enforcer().enforce(str(user.id), obj, act):
            raise HTTPException(status_code=403, detail="권한이 없습니다")
        return user

    return _dep
