"""엔티티 RAG(spec 149) — collections.kind/entity_schema + rag_chunks.meta

kind=document(기본)|entity. 데이터 변환 없음(기존 컬렉션 전부 document).

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-07-03 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collections", sa.Column("kind", sa.String(20), nullable=False, server_default="document"))
    op.add_column("collections", sa.Column("entity_schema", JSONB, nullable=True))
    op.add_column("rag_chunks", sa.Column("meta", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("rag_chunks", "meta")
    op.drop_column("collections", "entity_schema")
    op.drop_column("collections", "kind")
