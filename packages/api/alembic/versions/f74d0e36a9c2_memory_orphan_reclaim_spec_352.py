"""mem0 도달 불가 기억 회수 노브 (스펙 352).

mem0_memories는 별도 pgvector 테이블이라 우리 테이블과 FK가 없다 — user/session/agent를 지워도
그 기억은 남는다(청소부의 발자국). 도달 불가한 유령만 회수하는 배치의 유예 노브.

Revision ID: f74d0e36a9c2
Revises: e63c9d25f8b1
"""

import sqlalchemy as sa
from alembic import op

revision: str = "f74d0e36a9c2"
down_revision: str | None = "e63c9d25f8b1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("batch_config", sa.Column("memory_orphan_grace_days", sa.Integer(), nullable=True))
    op.add_column(
        "batch_config", sa.Column("memory_cleanup_cron", sa.String(length=120), nullable=True)
    )
    op.execute(
        "UPDATE batch_config SET memory_orphan_grace_days = 7, memory_cleanup_cron = '30 5 * * *' "
        "WHERE memory_orphan_grace_days IS NULL"
    )


def downgrade() -> None:
    op.drop_column("batch_config", "memory_cleanup_cron")
    op.drop_column("batch_config", "memory_orphan_grace_days")
