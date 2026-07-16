"""models.auth — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid
from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import (
    SQLAlchemyBaseAccessTokenTableUUID,
)
from sqlalchemy import (
    DateTime,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..audit import AuditMixin
from .base import Base, _pk


class User(SQLAlchemyBaseUserTableUUID, Base):
    """fastapi-users 유저(table=user). id/email/hashed_password/is_active/is_superuser/
    is_verified는 베이스에서 상속. source로 인증 출처(local/ldap/oidc)를 구분해 외부 provider
    drop-in 시 동일 테이블을 쓴다."""

    source: Mapped[str] = mapped_column(String(20), default="local", server_default="local")
    display_name: Mapped[str | None] = mapped_column(String(200), default=None)
    # 감사 믹스인 비적용(스펙 343 §1 — fastapi-users 소유 테이블). 기존 created_at은 그대로 유지한다.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    """DatabaseStrategy 세션 토큰 행(table=accesstoken). token PK + user_id FK(user.id, CASCADE) +
    created_at. 로그아웃 시 행 삭제 = 진짜 세션 무효화. (채팅 sessions와 충돌하지 않는 이름.)"""


class Role(AuditMixin, Base):
    """role 카탈로그 — UI 표시·관리용(어떤 role이 있나 나열). 할당의 진실 원천은 Casbin grouping
    policy(casbin_rule)지 이 테이블이 아니다."""

    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")


# ----------------------------- 배치 (스펙 038) -----------------------------
# 시스템과 격리된 별도 배치 서비스(`api.batch`)가 쓰는 두 테이블. learning 012: 운영 설정(보존창·
# 스케줄)은 env가 아니라 DB가 진실원. learning 033: Base.metadata에 매핑해 autogenerate가 외부
# 테이블(mem0_memories)을 안 건드리게 한다. 지배 스펙: docs/spec/archive/038-batch-foundation-session-cleanup.md
