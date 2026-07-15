"""block versioning spec 369

Revision ID: f79412647c2d
Revises: ee861d878e95
Create Date: 2026-07-15 23:16:28.285438

스펙 369 — 블록 버전화: 5종 블록 테이블에 version 컬럼 + 공유 폴리모픽 이력 block_versions.
autogenerate 산출물에서 런타임 소유 테이블(checkpoints·mem0_memories·casbin_rule) drop과
무관 인덱스 churn은 트림(learning 364). v1 백필은 앱 부트의 ensure_v1_rows(멱등)가 담당 —
payload 형태 정의를 SQL로 중복하지 않기 위함(단일 출처=block_versions.py).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f79412647c2d'
down_revision: Union[str, Sequence[str], None] = 'ee861d878e95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BLOCK_TABLES = ("prompts", "memory_types", "mcp_servers", "models", "providers")


def upgrade() -> None:
    op.create_table(
        "block_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("block_pk", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "block_pk", "version", name="uq_block_version"),
    )
    op.create_index(
        op.f("ix_block_versions_block_pk"), "block_versions", ["block_pk"], unique=False
    )
    for table in _BLOCK_TABLES:
        op.add_column(
            table, sa.Column("version", sa.Integer(), server_default="1", nullable=False)
        )


def downgrade() -> None:
    for table in reversed(_BLOCK_TABLES):
        op.drop_column(table, "version")
    op.drop_index(op.f("ix_block_versions_block_pk"), table_name="block_versions")
    op.drop_table("block_versions")
