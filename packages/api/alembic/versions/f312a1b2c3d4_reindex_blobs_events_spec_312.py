"""document_blobs + collection_reindex_events (스펙 312 — 재인덱싱·재청킹 원본 보존과 이력)

Revision ID: f312a1b2c3d4
Revises: f240a1b2c3d4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f312a1b2c3d4"
down_revision = "f240a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 원본 바이트 보존(재청킹 필수) — Document와 1:1(document_id=PK), 문서 삭제 시 CASCADE.
    op.create_table(
        "document_blobs",
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id"),
    )
    # 재인덱싱 이력 — 모델·청크 정책 계보(성공/실패 모두). 컬렉션 삭제 시 CASCADE.
    op.create_table(
        "collection_reindex_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_model_id", UUID(as_uuid=True), nullable=True),
        sa.Column("from_model_name", sa.String(200), nullable=True),
        sa.Column("to_model_id", UUID(as_uuid=True), nullable=True),
        sa.Column("to_model_name", sa.String(200), nullable=True),
        sa.Column("from_chunk_size", sa.Integer(), nullable=True),
        sa.Column("from_chunk_overlap", sa.Integer(), nullable=True),
        sa.Column("to_chunk_size", sa.Integer(), nullable=True),
        sa.Column("to_chunk_overlap", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collection_reindex_events_collection_id",
        "collection_reindex_events",
        ["collection_id"],
    )
    op.create_index(
        "ix_collection_reindex_events_owner_id",
        "collection_reindex_events",
        ["owner_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_collection_reindex_events_owner_id", "collection_reindex_events")
    op.drop_index("ix_collection_reindex_events_collection_id", "collection_reindex_events")
    op.drop_table("collection_reindex_events")
    op.drop_table("document_blobs")
