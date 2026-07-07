"""mcp_servers.updated_at 추가 (스펙 216)

빌딩 블록 '수정일' 열 배선 — McpServer에 updated_at 컬럼 추가. Persona는 이미 보유.
onupdate는 ORM-side(앱)라 DB 트리거 불요 — 컬럼만 server_default=now()로 추가하면
기존 행은 마이그레이션 시각으로 백필되고, 이후 편집(PUT)이 ORM으로 갱신한다.

Revision ID: f212a1b2c3d4
Revises: f211a1b2c3d4
Create Date: 2026-07-07
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f212a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "f211a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "updated_at")
