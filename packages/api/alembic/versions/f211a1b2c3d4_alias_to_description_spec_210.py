"""alias→description 개명 (스펙 210)

personas/mcp_servers/agents: alias 컬럼을 description으로 rename(값 보존).
collections: description(Text)이 이미 있으므로 병합 — description이 비어 있으면 alias 값을
채운 뒤 alias drop(별명 값 소실 0, 둘 다 있으면 기존 description 우선).

Revision ID: f211a1b2c3d4
Revises: f210a1b2c3d4
Create Date: 2026-07-07
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f211a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "f210a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 3종 rename — 타입(String(200))·값 그대로, 이름만.
    op.alter_column("personas", "alias", new_column_name="description")
    op.alter_column("mcp_servers", "alias", new_column_name="description")
    op.alter_column("agents", "alias", new_column_name="description")
    # collections: 병합 후 drop(소실 0 — 설명이 비어 있을 때만 별명으로 채움).
    op.execute(
        "UPDATE collections SET description = alias "
        "WHERE alias IS NOT NULL AND alias <> '' AND (description IS NULL OR description = '')"
    )
    op.drop_column("collections", "alias")


def downgrade() -> None:
    op.alter_column("personas", "description", new_column_name="alias")
    op.alter_column("mcp_servers", "description", new_column_name="alias")
    op.alter_column("agents", "description", new_column_name="alias")
    # collections 병합은 비가역(어느 값이 별명이었는지 소실) — 컬럼만 복원.
    op.add_column("collections", sa.Column("alias", sa.String(200), nullable=True))
