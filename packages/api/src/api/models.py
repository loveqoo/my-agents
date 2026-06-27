"""에이전트 서비스 도메인 테이블.

빌딩 블록(페르소나·메모리타입·벡터테이블·권한·MCP 서버)은 개별 테이블,
에이전트는 컬럼 + config jsonb + agent_versions, 그리고 세션/메시지/승인.
지배 스펙: docs/spec/007-real-agent-service.md
"""

import os
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# RAG 청크 벡터 차원 — pgvector 컬럼은 생성 시 차원이 고정되므로(스펙 020 함정3) 이 값이 곧
# `rag_chunks.embedding` 컬럼 차원이자 Collection 생성 시 허용 차원의 단일 출처다. 기본 임베딩
# 모델(multilingual-e5-large=1024) 출력과 일치해야 한다. mem0(_EMBED_DIMS)와 같은 1024 기본.
RAG_EMBED_DIMS = int(os.environ.get("RAG_EMBED_DIMS", os.environ.get("MEM0_EMBED_DIMS", "1024")))


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


class Collection(Base):
    """RAG 지식 컬렉션 — 문서를 임베딩해 의미 검색에 쓰는 단위(스펙 036, vector_tables 재생).

    임베딩 모델 1개로 묶이며 `dims`는 생성 시 probe 실측으로 고정(차원 트랩 대응, 스펙 020 함정3).
    하위 Document·Chunk를 CASCADE로 소유한다. 에이전트 config의 `vectorTables`(이름 목록)가 이
    컬렉션을 참조한다 — 런타임 retrieval 배선은 037.
    """

    __tablename__ = "collections"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # 이 컬렉션을 만들 때 쓴 임베딩 모델 — 037 질의 시 같은 모델로 임베딩해야 정합. 모델 삭제 차단(RESTRICT).
    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"), nullable=False
    )
    dims: Mapped[int] = mapped_column(Integer)  # 생성 시 probe 실측으로 박제(= rag_chunks 컬럼 차원)
    # 청킹도 전략 — 컬렉션별로 사용자 수정 가능(기본 1000자/200 오버랩). 인제스트 시 이 값을 읽어 분할.
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=200)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)  # 비정규화 집계 캐시
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="empty")  # empty|ingesting|ready|error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    embedding_model: Mapped["ModelConfig"] = relationship()
    documents: Mapped[list["Document"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", passive_deletes=True
    )


class Document(Base):
    """RAG 컬렉션에 인제스트된 업로드 파일(스펙 036). 청크를 CASCADE로 소유."""

    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _pk()
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(400))
    content_type: Mapped[str | None] = mapped_column(String(120), default=None)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="parsing")  # parsing|embedding|ready|error
    error: Mapped[str | None] = mapped_column(Text, default=None)  # 실패 사유 보존(no silent death)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    collection: Mapped["Collection"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(Base):
    """문서 청크 + 임베딩 벡터(전용 pgvector 저장소, 스펙 036).

    `embedding`은 `Vector(RAG_EMBED_DIMS)`로 차원 고정. insert 전 길이 검증으로 차원 불일치를
    명시적으로 막는다(조용한 죽음 방지). HNSW cosine 인덱스는 037 retrieval에서 본격 사용.
    """

    __tablename__ = "rag_chunks"
    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 질의 필터용 비정규화(037에서 컬렉션 단위 검색) — document 경유 join 없이 바로 필터.
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, default=0)  # 문서 내 순번
    text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float]] = mapped_column(Vector(RAG_EMBED_DIMS))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")


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


# ----------------------------- 배치 (스펙 038) -----------------------------
# 시스템과 격리된 별도 배치 서비스(`api.batch`)가 쓰는 두 테이블. learning 012: 운영 설정(보존창·
# 스케줄)은 env가 아니라 DB가 진실원. learning 033: Base.metadata에 매핑해 autogenerate가 외부
# 테이블(mem0_memories)을 안 건드리게 한다. 지배 스펙: docs/spec/038-batch-foundation-session-cleanup.md
class BatchRun(Base):
    """배치 실행 감사 로그 — 매 run을 박제(시작→ok/error + 건수). 가시성·idempotency 추적."""

    __tablename__ = "batch_runs"
    id: Mapped[uuid.UUID] = _pk()
    job_name: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|error
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict | None] = mapped_column(JSONB, default=None)  # 건수 등 결과
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class BatchConfig(Base):
    """배치 운영 설정(싱글톤 1행). 값은 기본 NULL → 아무 것도 자동 발화·삭제하지 않는다(보수적 기본).

    `session_retention_days`: NULL=비활성. N이면 last_activity가 N일보다 오래된 세션을 정리 대상으로.
    `session_cleanup_cron`: 격리 배치 서비스의 내부 스케줄러가 읽는 cron식(예 "0 3 * * *"). NULL=미등록.
    `memory_consolidation_threshold`: NULL=비활성. 의미상 ≥2 — user_id 기억이 이 수를 넘은 유저만
      통합 대상(스펙 039). 0/1은 거의 모든 유저를 매번 통합하는 파괴적 churn이라 API에서 ge=2로 거르고
      jobs에서도 <2 가드(learning 037 — 파괴적 노브 바닥).
    `memory_consolidation_cron`: 메모리 통합 작업의 cron식. NULL=미등록.
    """

    __tablename__ = "batch_config"
    id: Mapped[uuid.UUID] = _pk()
    session_retention_days: Mapped[int | None] = mapped_column(Integer, default=None)
    session_cleanup_cron: Mapped[str | None] = mapped_column(String(120), default=None)
    memory_consolidation_threshold: Mapped[int | None] = mapped_column(Integer, default=None)
    memory_consolidation_cron: Mapped[str | None] = mapped_column(String(120), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemorySnapshot(Base):
    """유저 메모리 통합(스펙 039) 전 원본 기억의 백업·롤백 앵커. 통합 작업이 원본을 삭제하기 전에
    여기 박제(text 원문 보존)한다 → 잘못돼도 수동 복원 가능(스냅샷 text를 add(infer=False)로 재적재).

    batch_run_id는 어느 실행이 만든 백업인지 추적용 FK. 실행 감사행(batch_runs)이 지워져도 스냅샷은
    살아남아야 하므로 ondelete SET NULL(롤백 데이터는 감사행 수명과 독립). user_id=mem0 축(str),
    mem_id=원본 mem0 기억 id. 이 테이블은 mem0가 아니라 우리가 소유·관리한다(learning 033).
    """

    __tablename__ = "memory_snapshots"
    id: Mapped[uuid.UUID] = _pk()
    batch_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch_runs.id", ondelete="SET NULL"), default=None, index=True
    )
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    mem_id: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
