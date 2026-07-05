"""approval resolution audit (spec 181)

resolve 시 *언제·누가* 처리했는지를 Approval에 스탬프 — 승인 내역(감사) 화면의 진실 원천.
resolved_at=처리 시각, resolved_by=처리자 user_id(요청자 user_id와 같으면 본인 승인, 다르면 관리자).
둘 다 nullable — 이 마이그레이션 이전 행·미처리(pending) 행은 NULL(하위호환).

Revision ID: a181c2d3e4f5
Revises: a177b3c4d5e6
Create Date: 2026-07-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a181c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "a177b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("approvals", sa.Column("resolved_by", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "resolved_by")
    op.drop_column("approvals", "resolved_at")
