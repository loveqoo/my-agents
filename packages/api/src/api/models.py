"""에이전트 서비스 도메인 테이블.

빌딩 블록(페르소나·메모리타입·벡터테이블·권한·MCP 서버)은 개별 테이블,
에이전트는 컬럼 + config jsonb + agent_versions, 그리고 세션/메시지/승인.
지배 스펙: docs/spec/007-real-agent-service.md
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# ----------------------------- 빌딩 블록 -----------------------------
class Persona(Base):
    __tablename__ = "personas"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    tone: Mapped[str | None] = mapped_column(String(200), default=None)
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryType(Base):
    """메모리 타입 카탈로그 (단기(인-컨텍스트)/장기 기억(mem0)). 시드 고정값 — 스펙 020."""

    __tablename__ = "memory_types"
    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str | None] = mapped_column(String(80), default=None)
    body: Mapped[str] = mapped_column(Text, default="")


class VectorTable(Base):
    """임베딩 데이터셋 메타데이터 (의미 검색 지식 소스)."""

    __tablename__ = "vector_tables"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    model: Mapped[str | None] = mapped_column(String(120), default=None)
    source: Mapped[str | None] = mapped_column(String(200), default=None)
    dims: Mapped[int | None] = mapped_column(Integer, default=None)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="synced")
    body: Mapped[str] = mapped_column(Text, default="")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)
    scope: Mapped[str | None] = mapped_column(String(80), default=None)
    approver: Mapped[str] = mapped_column(String(20), default="user")  # user | admin
    body: Mapped[str] = mapped_column(Text, default="")


class Provider(Base):
    """LLM provider = 엔드포인트 + 자격증명 (스펙 035). 모델 1:N로 매달림.

    provider 1회 등록 → 하위 모델 다수가 base_url/api_key를 공유(중복 제거).
    `protocol`은 와이어 포맷(openai-compatible 등)으로, 모델의 `kind`(chat/embedding)와 별개 축.
    """

    __tablename__ = "providers"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)  # 표시·참조용 이름
    protocol: Mapped[str] = mapped_column(String(40), default="openai-compatible")
    base_url: Mapped[str] = mapped_column(String(400), default="")
    api_key: Mapped[str | None] = mapped_column(String(400), default=None)  # 암호화 저장
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    models: Mapped[list["ModelConfig"]] = relationship(back_populates="provider")


class ModelConfig(Base):
    """LLM/임베딩 모델 설정 레지스트리. 에이전트가 이름으로 골라 실행에 사용.

    연결처(base_url/api_key)는 자신이 매달린 `Provider`에서 상속한다(스펙 035).
    """

    __tablename__ = "models"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)  # 표시·참조용 이름
    # provider 삭제 시 매달린 모델이 있으면 차단(RESTRICT) — 실수로 모델 고아화 방지.
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(200), default="")  # API에 보내는 모델 id
    kind: Mapped[str] = mapped_column(String(20), default="chat")  # chat | embedding
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)  # temperature 등
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider: Mapped["Provider"] = relationship(back_populates="models")


class McpServer(Base):
    __tablename__ = "mcp_servers"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)
    source: Mapped[str] = mapped_column(String(20), default="local")  # local | external
    transport: Mapped[str] = mapped_column(String(20), default="stdio")  # stdio | http
    url: Mapped[str | None] = mapped_column(String(400), default=None)
    endpoint: Mapped[str | None] = mapped_column(String(400), default=None)
    tools: Mapped[list] = mapped_column(JSONB, default=list)
    enabled_tools: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(40), default="connected")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    auth: Mapped[str | None] = mapped_column(String(120), default=None)


# ----------------------------- 에이전트 -----------------------------
class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = _pk()
    agent_id: Mapped[str] = mapped_column(String(80), unique=True)  # 외부 식별자 agt_...
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), default="ui")  # ui | code | external(A2A 카드)
    model: Mapped[str] = mapped_column(String(120), default="local-mlx")
    persona: Mapped[str] = mapped_column(Text, default="")  # 해석된 페르소나 본문(서빙용)
    history_depth: Mapped[int] = mapped_column(Integer, default=20)
    # config = {model, persona, memories[], vectorTables[], permissions[], mcps[], historyDepth}
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    exposed: Mapped[dict] = mapped_column(JSONB, default=lambda: {"a2a": False})
    status: Mapped[str] = mapped_column(String(20), default="idle")  # online | idle | offline
    active_version: Mapped[str | None] = mapped_column(String(40), default=None)
    # 코드 정의 에이전트 메타 (source == 'code')
    endpoint: Mapped[str | None] = mapped_column(String(400), default=None)
    token: Mapped[str | None] = mapped_column(String(200), default=None)  # 마스킹 저장
    runtime: Mapped[str | None] = mapped_column(String(200), default=None)
    repo: Mapped[str | None] = mapped_column(String(200), default=None)
    commit: Mapped[str | None] = mapped_column(String(80), default=None)
    registered_at: Mapped[str | None] = mapped_column(String(40), default=None)
    last_sync: Mapped[str | None] = mapped_column(String(40), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="AgentVersion.created_at.desc()"
    )


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    id: Mapped[uuid.UUID] = _pk()
    agent_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active | archived
    note: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="versions")


# ----------------------------- 세션/메시지 -----------------------------
class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[str] = mapped_column(String(80), unique=True)  # sess_...
    agent_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(80), default="debug-console")
    # 이 세션에서 마지막으로 쓰인 non-empty userId(mem0 user_id 축). distinct 목록 출처 — 스펙 021.
    # 세션당 1값이라 도중 변경 시 마지막 값만 남는다(목록 생성엔 충분, 합의된 한계).
    user_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    turns: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = _pk()
    session_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    trace: Mapped[dict | None] = mapped_column(JSONB, default=None)  # 인스펙터용 트레이스
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[Session] = relationship(back_populates="messages")


# ----------------------------- 승인 큐 -----------------------------
class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = _pk()
    approval_id: Mapped[str] = mapped_column(String(80), unique=True)  # apr_...
    session_id: Mapped[str | None] = mapped_column(String(80), default=None)
    agent_pk: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    agent_name: Mapped[str] = mapped_column(String(200), default="")
    permission: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(120), default="")
    args: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    checkpoint: Mapped[str | None] = mapped_column(String(80), default=None)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ----------------------------- 인증·권한 (스펙 031) -----------------------------
# 인증은 fastapi-users 규약을 차용한다. User/AccessToken 베이스 믹스인을 우리 Base와 결합해
# 같은 metadata(alembic·create_all)에 매핑한다. 테이블명은 라이브러리 기본값(user/accesstoken).
# 권한(RBAC)은 Casbin이 담당하며 role 할당의 진실 원천은 casbin_rule(어댑터가 런타임 생성)이다.
# roles는 UI 표시·관리용 가벼운 카탈로그일 뿐(할당 저장소가 아님).
from fastapi_users.db import SQLAlchemyBaseUserTableUUID  # noqa: E402
from fastapi_users_db_sqlalchemy.access_token import (  # noqa: E402
    SQLAlchemyBaseAccessTokenTableUUID,
)


class User(SQLAlchemyBaseUserTableUUID, Base):
    """fastapi-users 유저(table=user). id/email/hashed_password/is_active/is_superuser/
    is_verified는 베이스에서 상속. source로 인증 출처(local/ldap/oidc)를 구분해 외부 provider
    drop-in 시 동일 테이블을 쓴다."""

    source: Mapped[str] = mapped_column(String(20), default="local", server_default="local")
    display_name: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    """DatabaseStrategy 세션 토큰 행(table=accesstoken). token PK + user_id FK(user.id, CASCADE) +
    created_at. 로그아웃 시 행 삭제 = 진짜 세션 무효화. (채팅 sessions와 충돌하지 않는 이름.)"""


class Role(Base):
    """role 카탈로그 — UI 표시·관리용(어떤 role이 있나 나열). 할당의 진실 원천은 Casbin grouping
    policy(casbin_rule)지 이 테이블이 아니다."""

    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
