"""schemas.admin — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

import uuid

# ----------------------------- 인증·권한 (스펙 031) -----------------------------
# fastapi-users Pydantic 스키마. BaseUser는 id/email/is_active/is_superuser/is_verified 포함.
from fastapi_users import schemas as _fu_schemas
from pydantic import BaseModel, Field

from .base import ORM


class UserRead(_fu_schemas.BaseUser[uuid.UUID]):
    source: str
    display_name: str | None = None


class UserCreate(_fu_schemas.BaseUserCreate):
    display_name: str | None = None


class UserUpdate(_fu_schemas.BaseUserUpdate):
    display_name: str | None = None


class RoleAssignIn(BaseModel):
    role: str


class RoleOut(BaseModel):
    name: str
    description: str = ""
    model_config = ORM


class PolicyIn(BaseModel):
    """능력 부여/회수 입력(스펙 177 P3). subject=역할명 또는 유저 id, object=`capability:...`.

    보안 경계는 라우트(user_admin.grant_policy)가 강제 — object는 `capability:`로 시작하고
    와일드카드(*) 불가, action은 invoke 고정. 이 UI로 임의 리소스 권한·(*,*) 상승을 못 준다."""

    subject: str = Field(min_length=1, max_length=200)  # 역할명(member 등) 또는 유저 UUID 문자열
    object: str = Field(min_length=1, max_length=200)  # capability:{kind}[:{name}]
    action: str = Field(default="invoke", max_length=40)


class PolicyOut(BaseModel):
    subject: str
    object: str
    action: str


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    source: str
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    model_config = ORM
