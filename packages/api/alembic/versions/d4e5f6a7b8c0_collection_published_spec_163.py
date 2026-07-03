"""add published to collections (spec 163 — 컬렉션 사용 공개)

컬렉션에 published(사용 공개) 추가. True면 타 작성자 에이전트도 배선 가능(agent_may_wire rule 4,
스펙 113). 기존 행은 false=비공개(fail-closed 무회귀 — 지금까지 못 쓰던 걸 열지 않는다). owner_id
(관리 축)와 직교: 소유는 그대로 두고 "사용만" 공개. MCP published(스펙 152) 미러.

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("collections", "published")
