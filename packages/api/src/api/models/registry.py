"""models.registry — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..audit import AuditMixin
from .base import Base, _pk


class Provider(AuditMixin, Base):
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
    # 표시·배지용(스펙 047 #6) — local=실서버, mock=내장 테스트목, remote=외부. 라벨 혼란 해소.
    kind: Mapped[str] = mapped_column(String(20), default="remote", server_default="remote")
    description: Mapped[str] = mapped_column(
        String(400), default="", server_default=""
    )  # 한 줄 설명
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 스펙 369

    models: Mapped[list["ModelConfig"]] = relationship(back_populates="provider")


class ModelConfig(AuditMixin, Base):
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
    # kind당 기본 1개 DB 불변식(스펙 150 — 동시 지정 레이스 봉인). alembic(a1b2c3d4e5f7)과 정합 —
    # metadata에도 같은 인덱스를 선언해 autogenerate diff 0 유지.
    __table_args__ = (
        Index(
            "uq_models_default_per_kind", "kind", unique=True, postgresql_where=text("is_default")
        ),
    )
    params: Mapped[dict] = mapped_column(JSONB, default=dict)  # temperature 등(런타임 파라미터)
    # 능력 선언(스펙 408, 2층 원칙의 능력 층 — 오버라이드 불가): 서빙 서버가 할 수 있는 것의 사실
    # 기록. streaming=false면 비스트리밍 안전 실행, vision은 C안 게이트 선반영, thinking=모드 보유.
    capabilities: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"streaming": True, "thinking": False, "vision": False},
        server_default='{"streaming": true, "thinking": false, "vision": false}',
    )
    # models.dev 카탈로그 파생 메타(스펙 047 #7) — context·modalities·cost·capabilities. params와 분리.
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 스펙 369

    provider: Mapped["Provider"] = relationship(back_populates="models")
