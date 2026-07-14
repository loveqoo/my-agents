"""처리된 승인 보존정책 (스펙 350).

위험 도구 호출마다 approvals 1행이 쌓이는데 삭제 코드가 리포 전체에 없었다.
pending은 재개 근거라 대상이 아니다(방치 pending은 346 스윕이 expired로 바꾼 뒤 이 보존기간을 탄다).

Revision ID: d52b8c14e7a6
Revises: c41a9e77b2d3
"""

import sqlalchemy as sa
from alembic import op

revision: str = "d52b8c14e7a6"
down_revision: str | None = "c41a9e77b2d3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("batch_config", sa.Column("approval_retention_days", sa.Integer(), nullable=True))
    op.add_column(
        "batch_config", sa.Column("approval_cleanup_cron", sa.String(length=120), nullable=True)
    )
    op.execute(
        "UPDATE batch_config SET approval_retention_days = 30, approval_cleanup_cron = '30 4 * * *' "
        "WHERE approval_retention_days IS NULL"
    )


def downgrade() -> None:
    op.drop_column("batch_config", "approval_cleanup_cron")
    op.drop_column("batch_config", "approval_retention_days")
