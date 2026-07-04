"""드롭 permissions 테이블 (스펙 177 P3) — 죽은 "권한" 개념 정리.

config.permissions[]는 런타임서 강제된 적이 없고(선언만), Permission.approver는 실 승인
결정과 무관(P2에서 Approval.approver로 이관). "능력/역할/승인" 3개념으로 수렴하며 이 테이블을
드롭한다. 되돌리기(downgrade)는 스키마만 복원(시드 데이터는 seed가 더는 채우지 않음).
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a177b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "a177b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("permissions")


def downgrade() -> None:
    # 스키마 복원(스펙 148 정합) — 데이터는 복구하지 않는다.
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=True),
        sa.Column("scope", sa.String(length=80), nullable=True),
        sa.Column("approver", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
