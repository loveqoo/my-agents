"""add approvals.user_id (spec 066 — owner self-승인)

승인 요청 주체(auth User UUID str)를 기록한다. owner self-승인 인가(permission RBAC 3-way)의
대조 기준. 기존 행은 NULL로 남아 **admin 전용**으로 fail-closed(소급 채움 없음 — 레거시 발이
일반 유저에게 self-resolvable로 열리면 안 된다). user_id로 list를 본인 스코핑하므로 인덱스 추가.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("user_id", sa.String(length=80), nullable=True))
    op.create_index("ix_approvals_user_id", "approvals", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_user_id", table_name="approvals")
    op.drop_column("approvals", "user_id")
