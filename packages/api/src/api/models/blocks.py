"""models.blocks — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid

from sqlalchemy import (
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..audit import AuditMixin
from .base import Base, _pk


# ----------------------------- 빌딩 블록 -----------------------------
class Prompt(AuditMixin, Base):
    __tablename__ = "prompts"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)  # 식별 이름(규칙, 스펙 148)
    # 설명(선택, 스펙 210) — 구 별명(alias) 개명: 표시는 name 단독, 설명은 툴팁 등 부가정보.
    description: Mapped[str | None] = mapped_column(String(200), default=None)
    tone: Mapped[str | None] = mapped_column(String(200), default=None)
    body: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 스펙 369


class MemoryType(AuditMixin, Base):
    """메모리 타입 카탈로그 (단기(인-컨텍스트)/장기 기억(mem0)). 시드 고정값 — 스펙 020."""

    __tablename__ = "memory_types"
    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str | None] = mapped_column(String(80), default=None)
    body: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 스펙 369


class BlockVersion(AuditMixin, Base):
    """블록 버전 이력(스펙 369) — 5종 블록 공유 폴리모픽 append-only 이력.

    payload = 그 버전의 저작 내용 스냅샷(운영 상태·비밀 제외 — 경계는 block_versions.payload_for가
    단일 출처). kind별 테이블이 달라 FK 불가 — 블록 삭제 시 이력은 앱 레벨 같은 트랜잭션에서 삭제.
    UNIQUE(kind, block_pk, version)이 동시 편집 이중 append를 막는다(충돌=409).
    """

    __tablename__ = "block_versions"
    __table_args__ = (UniqueConstraint("kind", "block_pk", "version", name="uq_block_version"),)
    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String(20))  # prompt|memory-type|mcp-server|model|provider
    block_pk: Mapped[uuid.UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
