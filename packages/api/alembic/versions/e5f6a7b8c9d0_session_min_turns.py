"""session retention: batch_config.min_session_turns (spec 049, #10)

턴 기준 세션 정리 정책. batch_config에 min_session_turns 1컬럼 추가 — NULL=비활성.
N이면 turns<N인 이탈 세션을 정리 대상으로(활성 보호는 jobs의 IDLE_GUARD가 담당).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-28 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("batch_config", sa.Column("min_session_turns", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("batch_config", "min_session_turns")
