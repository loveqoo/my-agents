"""실행 이력 보존정책 (스펙 351).

eval_runs · batch_runs · memory_snapshots — 셋 다 "무슨 일이 있었나"의 기록인데 삭제 경로가 없었다.
스펙 348로 배치가 실제로 돌기 시작해 batch_runs가 매시 쌓이므로 청소부의 발자국도 치운다.

Revision ID: e63c9d25f8b1
Revises: d52b8c14e7a6
"""

import sqlalchemy as sa
from alembic import op

revision: str = "e63c9d25f8b1"
down_revision: str | None = "d52b8c14e7a6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("batch_config", sa.Column("history_retention_days", sa.Integer(), nullable=True))
    op.add_column(
        "batch_config", sa.Column("history_cleanup_cron", sa.String(length=120), nullable=True)
    )
    op.execute(
        "UPDATE batch_config SET history_retention_days = 90, history_cleanup_cron = '0 5 * * *' "
        "WHERE history_retention_days IS NULL"
    )


def downgrade() -> None:
    op.drop_column("batch_config", "history_cleanup_cron")
    op.drop_column("batch_config", "history_retention_days")
