"""drop collection.published (spec 172)

RAG 컬렉션에서 공개/비공개(published) 개념 제거 — 사용은 전부 공용(로그인한 누구나),
관리는 소유자만. 스펙 163의 published 축을 걷어낸다.

Revision ID: f6a7b8c9d1e2
Revises: e5f6a7b8c9d1
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d1e2"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("collections", "published")


def downgrade() -> None:
    op.add_column(
        "collections",
        sa.Column("published", sa.Boolean(), server_default="false", nullable=False),
    )
