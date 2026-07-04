"""approval impl snapshot (spec 171)

승인 재개 impl-drift 명시 가드용 — 생성 시점 impl 키 스냅샷 컬럼.
"" = 기본(DefaultUiAgent), "key" = 커스텀, NULL = 이 마이그레이션 이전 행(대조 스킵).

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable — 기존 pending/결재 행은 NULL(대조 스킵, 하위호환). 신규 행만 생성 시 값이 박힌다.
    op.add_column("approvals", sa.Column("impl", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "impl")
