"""models.core — 도메인 테이블(스펙 379 분할·verbatim 이관)."""


from sqlalchemy import (
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..audit import AuditMixin
from .base import Base


class AppSetting(AuditMixin, Base):
    """앱 설정 키-값(스펙 153) — 관리자가 UI로 바꾸는 소수의 전역 설정(A2A org 등).
    키는 라우트의 닫힌 집합으로 통제(미지 키 400) — env는 배포 정체성, 여긴 운영 중 변경 값."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"v": <값>} 봉투(타입 유연)
