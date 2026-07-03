"""eval_runs에 model_name·group_id (spec 141 — 모델별 비교 실행)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-07-03 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column("model_name", sa.String(120), nullable=True))
    op.add_column("eval_runs", sa.Column("group_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_eval_runs_group_id", "eval_runs", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_group_id", table_name="eval_runs")
    op.drop_column("eval_runs", "group_id")
    op.drop_column("eval_runs", "model_name")
