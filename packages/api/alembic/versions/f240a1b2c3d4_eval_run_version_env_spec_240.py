"""eval_runs에 agent_version+env 추가 (스펙 240 — 평가의 버전 귀속·경량 환경 기록)

Revision ID: f240a1b2c3d4
Revises: f212a1b2c3d4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f240a1b2c3d4"
down_revision = "f212a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 실행 시점 활성 버전 박제(과거 행 NULL=미기록 — 정직 표기). env=경량 환경 기록(진단용 JSONB).
    op.add_column("eval_runs", sa.Column("agent_version", sa.String(20), nullable=True))
    op.add_column("eval_runs", sa.Column("env", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("eval_runs", "env")
    op.drop_column("eval_runs", "agent_version")
