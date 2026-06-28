"""destructive cleanup: batch_config.test_user_email_pattern (spec 050, #13)

테스트 유저 정리 정책. batch_config에 test_user_email_pattern 1컬럼 추가 — NULL=비활성.
SQL LIKE 패턴(예 "verify%@example.com")에 일치하는 유저를 user-cleanup 잡이 정리 대상으로.
파괴적이므로 바닥 3겹(`%`/빈 거부·keep-list·마지막 super 보존)은 jobs/API가 담당.

Revision ID: a6b7c8d9e0f1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-28 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "batch_config", sa.Column("test_user_email_pattern", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("batch_config", "test_user_email_pattern")
