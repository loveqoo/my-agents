"""models.agents — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..audit import AuditMixin
from .base import Base, _pk


class NodeTemplate(AuditMixin, Base):
    """노드 라이브러리(스펙 316) — 노드형 파이프라인 노드의 등록·공유 자산.

    (name, version) 단위로 존재하고 **발행 후 불변**(수정 API 없음 — 수정=새 버전 발행). 에이전트는
    `nodes[]`에 `{"ref": {"name", "version"}}`으로 버전을 핀 고정 참조한다 — 등록 노드를 개선해도
    기존 참조 에이전트는 흔들리지 않는다(테스트·출시 보호, 사용자 결정 2026-07-13). kind=code(코드
    노드, 스펙 317)만 동일 버전 덮어쓰기를 허용하는 의도된 탈출구를 가진다(본 스펙은 config만)."""

    __tablename__ = "node_templates"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120))  # 식별 이름(규칙, 스펙 148 준용)
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(20), default="config")  # config | code(스펙 317 예약)
    # 에이전트 저장 스키마의 노드 화이트리스트(_normalize_node)를 통과한 형태만 저장(검증 재사용).
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    description: Mapped[str | None] = mapped_column(String(200), default=None)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_node_templates_name_version"),)


# ----------------------------- 에이전트 -----------------------------
class Agent(AuditMixin, Base):
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = _pk()
    agent_id: Mapped[str] = mapped_column(String(80), unique=True)  # 외부 식별자 agt_...
    name: Mapped[str] = mapped_column(String(200), unique=True)  # 식별 이름(규칙+유니크, 스펙 148)
    # 설명(선택, 스펙 210) — 구 별명(alias) 개명: 표시는 name 단독, 설명은 툴팁 등 부가정보.
    description: Mapped[str | None] = mapped_column(String(200), default=None)
    source: Mapped[str] = mapped_column(String(20), default="ui")  # ui | code | external(A2A 카드)
    model: Mapped[str] = mapped_column(
        String(120), default="mock-llm"
    )  # 미지정 시 기본 모델(스펙 059)
    prompt: Mapped[str] = mapped_column(Text, default="")  # 해석된 프롬프트 본문(서빙용)
    history_depth: Mapped[int] = mapped_column(Integer, default=20)
    # config = {model, prompt, memories[], vectorTables[], mcps[], historyDepth}
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
    # 소유자(스펙 112) — None=레거시/admin=admin 전용(fail-closed, 070). 생성 시 스탬프·이전 금지(069).
    owner_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)

    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by="AgentVersion.created_at.desc()",
    )


class AgentVersion(AuditMixin, Base):
    """에이전트 불변 단조 버전(스펙 370 — 구 draft/active/archived 상태기계 폐기).

    상태는 에이전트의 오픈 포인터(Agent.active_version) 하나 — 버전 자신은 ever_opened(오픈 이력,
    한 번 오픈되면 영구 불변 보호)와 pins(블록 버전 못박기 `{"<kind>:<name>": <ver>}`)만 가진다.
    미오픈 스크래치는 에이전트당 최대 1개(편집이 대체) — 구 단일 초안 불변식의 후계.
    """

    __tablename__ = "agent_versions"
    id: Mapped[uuid.UUID] = _pk()
    agent_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(40))
    ever_opened: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    pins: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    note: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)

    agent: Mapped[Agent] = relationship(back_populates="versions")


# ----------------------------- 세션/메시지 -----------------------------
