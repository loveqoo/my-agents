"""fastapi-users 배선 — 유저 관리 + 서버측 세션 쿠키 인증.

인증은 라이브러리(fastapi-users)를 차용한다(스펙 031). 세션은 서버측 쿠키:
`CookieTransport` + `DatabaseStrategy`(accesstoken 테이블의 불투명 토큰 행) → 로그아웃 시
행 삭제 = 진짜 무효화(JWT-in-cookie 아님). 비밀번호는 Argon2(pwdlib, fastapi-users 기본).

`SECRET`(리셋/검증 토큰 서명용)은 env `AUTH_SECRET` → `.dev/.auth_secret`(없으면 생성·영속·
gitignore) 순으로 로드한다(기존 .api_token 패턴 — 스펙 011/015).

지배 스펙: docs/spec/031-multi-user-auth-and-pluggable-providers.md
"""

import logging
import os
import secrets
import uuid
from functools import lru_cache
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import (
    AccessTokenDatabase,
    DatabaseStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import AccessToken, User

log = logging.getLogger("api.users")

# 세션 수명(초). idle/absolute 구분 없이 단일 수명(1차 — 스펙 031 범위). 기본 7일.
SESSION_LIFETIME_SECONDS = int(os.environ.get("AUTH_SESSION_LIFETIME", str(7 * 24 * 3600)))


@lru_cache(maxsize=1)
def _secret() -> str:
    """리셋/검증 토큰 서명 비밀. env 우선, 없으면 .dev/.auth_secret 생성·영속(gitignore)."""
    val = (os.environ.get("AUTH_SECRET") or "").strip()
    if val:
        return val
    # users.py = packages/api/src/api/users.py → parents[4] = repo 루트
    path = Path(__file__).resolve().parents[4] / ".dev" / ".auth_secret"
    if path.exists():
        existing = path.read_text().strip()
        if existing:
            return existing
    val = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(val)
    log.warning("AUTH_SECRET 미설정 — %s에 개발용 비밀 생성(gitignore).", path)
    return val


# ----------------------------- DB 어댑터 -----------------------------
async def get_user_db(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


async def get_access_token_db(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[SQLAlchemyAccessTokenDatabase, None]:
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


# ----------------------------- UserManager -----------------------------
class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = _secret()
    verification_token_secret = _secret()

    async def on_after_register(self, user: User, request=None) -> None:
        """가입(관리자 생성 포함) 직후 Casbin 기본 role(member) 부여."""
        # 지연 import: authz가 users를 참조하지 않지만 순환을 피하고 부팅 순서를 단순화.
        from .authz import assign_role

        # superuser는 enforce를 우회하고 seed_admin이 admin role을 부여하므로 member는 군더더기.
        if user.is_superuser:
            return
        try:
            await assign_role(str(user.id), "member")
        except Exception:  # noqa: BLE001 — role 부여 실패가 가입을 막지 않게(로그만)
            log.warning("member role 부여 실패 user=%s", user.id, exc_info=True)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


# ----------------------------- 인증 backend (쿠키) -----------------------------
# secure: 기본 True(보안 기본값). localhost는 브라우저가 secure context로 취급해 http에서도
# Secure 쿠키를 허용하므로 로컬 개발에 지장 없다. 비-localhost http 개발 시에만 0으로.
_cookie_secure = (os.environ.get("AUTH_COOKIE_SECURE", "true").strip().lower() != "false")
_cookie_samesite = os.environ.get("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
if _cookie_samesite not in ("lax", "strict", "none"):
    _cookie_samesite = "lax"

cookie_transport = CookieTransport(
    cookie_name="agentauth",
    cookie_max_age=SESSION_LIFETIME_SECONDS,
    cookie_secure=_cookie_secure,
    cookie_httponly=True,
    cookie_samesite=_cookie_samesite,
)


def get_database_strategy(
    access_token_db: AccessTokenDatabase[AccessToken] = Depends(get_access_token_db),
) -> DatabaseStrategy:
    return DatabaseStrategy(access_token_db, lifetime_seconds=SESSION_LIFETIME_SECONDS)


# provider 확장점: 후일 LDAP/OIDC backend를 이 리스트에 추가한다(스펙 031 §범위 밖).
auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# 세션 쿠키로 인증된 활성 유저 의존성.
current_active_user = fastapi_users.current_user(active=True)
# 미인증이면 None(통합 principal에서 머신 토큰 fallback에 사용).
current_user_optional = fastapi_users.current_user(active=True, optional=True)


async def seed_admin() -> None:
    """부팅 시 env(ADMIN_EMAIL/ADMIN_PASSWORD)로 superuser 시드 + admin role 부여.

    미설정이면 생성하지 않고 경고만 한다(fail-closed — 빈 관리자 자동생성 금지, 스펙 015/031).
    이미 있으면 admin role만 보장(멱등).
    """
    from .authz import assign_role
    from .db import SessionLocal
    from .schemas import UserCreate

    email = (os.environ.get("ADMIN_EMAIL") or "").strip()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        log.warning("ADMIN_EMAIL/ADMIN_PASSWORD 미설정 — 관리자 시드 생략(fail-closed).")
        return

    from fastapi_users.exceptions import UserAlreadyExists

    async with SessionLocal() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        manager = UserManager(user_db)
        existing = await user_db.get_by_email(email)
        if existing is not None:
            await assign_role(str(existing.id), "admin")
            return
        try:
            user = await manager.create(
                UserCreate(email=email, password=password, is_superuser=True, is_verified=True),
                safe=False,
            )
        except UserAlreadyExists:
            # 멀티워커 부팅 경쟁: 다른 워커가 먼저 생성. 재조회 후 admin role만 보장(멱등).
            user = await user_db.get_by_email(email)
            if user is None:
                raise
            await assign_role(str(user.id), "admin")
            return
        await assign_role(str(user.id), "admin")
        log.info("관리자 시드 생성: %s", email)
