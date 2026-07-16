"""models.eval — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..audit import AuditMixin
from .base import Base, _pk


class EvalDataset(AuditMixin, Base):
    """평가 문제집(스펙 137) — 케이스 묶음. kind='agent'|'rag'(RAG 컬렉션 평가 확장축, 후속)."""

    __tablename__ = "eval_datasets"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    kind: Mapped[str] = mapped_column(String(20), default="agent")  # agent|rag
    # 스펙 193: RAG 문제집의 대상 컬렉션 고정(실행 시 재선택 제거). kind='rag'만 사용, agent는 NULL.
    # 구버전 rag 문제집도 NULL(첫 실행 시 lazy 저장). 컬렉션 삭제 시 SET NULL(문제집 보존·연결만 끊김).
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
    )
    # 스펙 209 Phase 2: 피드백 수확 문제집이 어느 에이전트에서 왔나(idempotent 수확 — 에이전트당 1개
    # 문제집 재사용). 일반 문제집=NULL. 에이전트 삭제 시 SET NULL(문제집 보존·연결만 끊김).
    source_agent_pk: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
    )
    owner_id: Mapped[str | None] = mapped_column(
        String(80), index=True, default=None
    )  # 스펙 112 스탬프

    cases: Mapped[list["EvalCase"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class EvalCase(AuditMixin, Base):
    """평가 문제 — 입력(질문) + 선언적 asserts(JSONB: [{"type","arg"}]).

    type은 eval_harness의 닫힌 scorer 집합만 허용(미지 type은 API 검증 거부 — fail-closed).
    필수/금지 도구 채점은 trace_has/trace_lacks + canonical 토큰(mcp:/rag:/memory:used)으로 표현."""

    __tablename__ = "eval_cases"
    id: Mapped[uuid.UUID] = _pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)  # 에이전트에 보낼 질문
    asserts: Mapped[list] = mapped_column(JSONB, default=list)
    order_idx: Mapped[int] = mapped_column(Integer, default=0)

    dataset: Mapped["EvalDataset"] = relationship(back_populates="cases")


class EvalRun(AuditMixin, Base):
    """평가 실행 감사(BatchRun 미러) — running|ok|error + 점수. owner=실행자 스탬프."""

    __tablename__ = "eval_runs"
    id: Mapped[uuid.UUID] = _pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_pk: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    agent_name: Mapped[str | None] = mapped_column(
        String(120), default=None
    )  # 삭제 후 성적표 표기용 박제
    model_name: Mapped[str | None] = mapped_column(
        String(120), default=None
    )  # 모델 오버라이드 박제(스펙 141)
    # 버전 귀속(스펙 240, AgentOps A) — 실행 시점 활성 버전. NULL=과거 런(미기록, 정직 표기).
    agent_version: Mapped[str | None] = mapped_column(String(20), default=None)
    # 경량 환경 기록(스펙 240) — 모델 params·MCP 도구 목록·컬렉션 상태(docs/chunks/임베딩). **재현
    # 보장이 아니라 진단 단서**(완전 재현 스냅샷은 과설계로 기각 — RAG 인덱스 복제 비용).
    env: Mapped[dict | None] = mapped_column(JSONB, default=None)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        default=None, index=True
    )  # 모델 비교 그룹(스펙 141)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|error
    score: Mapped[float | None] = mapped_column(default=None)  # passed/total
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict | None] = mapped_column(JSONB, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    owner_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    results: Mapped[list["EvalCaseResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvalCaseResult(AuditMixin, Base):
    """케이스별 채점 결과 — assert별 상세(details)와 관측 요약(obs, 캡 적용)."""

    __tablename__ = "eval_case_results"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_name: Mapped[str] = mapped_column(String(200), nullable=False)
    case_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[list] = mapped_column(JSONB, default=list)  # [[assert_name, bool], ...]
    obs: Mapped[dict | None] = mapped_column(
        JSONB, default=None
    )  # {output(캡), trace_nodes, error}

    run: Mapped["EvalRun"] = relationship(back_populates="results")
