"""memory consolidation: batch_config cols + memory_snapshots (spec 039)

유저 메모리 통합·재적재(#6). batch_config에 통합 임계치·cron 2컬럼 추가,
memory_snapshots는 통합 전 원본 기억의 백업·롤백 앵커(통합 작업이 원본 삭제 전 박제).

Revision ID: c8d9e0f1a2b3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-27 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("batch_config", sa.Column("memory_consolidation_threshold", sa.Integer(), nullable=True))
    op.add_column("batch_config", sa.Column("memory_consolidation_cron", sa.String(length=120), nullable=True))

    op.create_table(
        "memory_snapshots",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_run_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.String(length=200), nullable=False),
        sa.Column("mem_id", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # 감사행이 지워져도 롤백 데이터는 살아남게 SET NULL(스냅샷 수명은 batch_runs와 독립).
        sa.ForeignKeyConstraint(["batch_run_id"], ["batch_runs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_memory_snapshots_batch_run_id", "memory_snapshots", ["batch_run_id"])
    op.create_index("ix_memory_snapshots_user_id", "memory_snapshots", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_snapshots_user_id", table_name="memory_snapshots")
    op.drop_index("ix_memory_snapshots_batch_run_id", table_name="memory_snapshots")
    op.drop_table("memory_snapshots")
    op.drop_column("batch_config", "memory_consolidation_cron")
    op.drop_column("batch_config", "memory_consolidation_threshold")
