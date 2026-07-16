"""models.mcp — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid

from sqlalchemy import (
    Boolean,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..audit import AuditMixin
from .base import Base, _pk


class McpServer(AuditMixin, Base):
    __tablename__ = "mcp_servers"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)  # 식별 이름(규칙, 스펙 148)
    # 설명(선택, 스펙 210) — 구 별명(alias) 개명: 표시는 name 단독, 설명은 툴팁 등 부가정보.
    description: Mapped[str | None] = mapped_column(String(200), default=None)
    source: Mapped[str] = mapped_column(String(20), default="local")  # local | external
    transport: Mapped[str] = mapped_column(String(20), default="stdio")  # stdio | http
    url: Mapped[str | None] = mapped_column(String(400), default=None)
    endpoint: Mapped[str | None] = mapped_column(String(400), default=None)
    tools: Mapped[list] = mapped_column(JSONB, default=list)
    enabled_tools: Mapped[list] = mapped_column(JSONB, default=list)
    # 도구 메타 스냅샷(스펙 151) — name→{description, params:[{name,type,required}]}. 탐색 시점 저장.
    tools_meta: Mapped[dict | None] = mapped_column(JSONB, default=None)
    status: Mapped[str] = mapped_column(String(40), default="connected")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    auth: Mapped[str | None] = mapped_column(
        String(400), default=None
    )  # 암호화 저장(Fernet, 스펙 054 F) — 응답은 마스킹
    # 소유자(스펙 112) — None=레거시/admin=admin 전용(fail-closed, 070). 생성 시 스탬프·이전 금지(069).
    owner_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 스펙 369
    # 수정일(스펙 216) — 빌딩 블록 '수정일' 열 배선. Prompt와 동일 패턴, onupdate는 ORM-side.
