"""batch foundation: batch_runs + batch_config (spec 038)

격리된 배치 서비스(`api.batch`)의 두 테이블. batch_runs는 매 실행 감사 로그,
batch_config는 운영 설정 싱글톤(보존창·cron, 기본 NULL=비활성).

Revision ID: a7b8c9d0e1f2
Revises: b2c3d4e5f6a7
Create Date: 2026-06-27 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_batch_runs_job_name", "batch_runs", ["job_name"])

    op.create_table(
        "batch_config",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_retention_days", sa.Integer(), nullable=True),
        sa.Column("session_cleanup_cron", sa.String(length=120), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("batch_config")
    op.drop_index("ix_batch_runs_job_name", table_name="batch_runs")
    op.drop_table("batch_runs")
