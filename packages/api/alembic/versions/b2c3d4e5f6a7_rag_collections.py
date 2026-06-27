"""rag collections — vector_tables(죽은 카탈로그)를 collections/documents/rag_chunks로 재생 (스펙 036)

죽은 mock 카탈로그 `vector_tables`를 제거하고, 실제 RAG 인제스트 저장소 3종을 만든다:
  - collections : 임베딩 모델 1개로 묶인 문서 묶음(차원 박제, 청킹 설정, 집계 캐시).
  - documents   : 컬렉션에 인제스트된 업로드 파일(상태/오류 보존).
  - rag_chunks  : 청크 + pgvector 임베딩(Vector(N) 차원 고정 + HNSW cosine 인덱스).

차원(N)은 `RAG_EMBED_DIMS`(기본 1024) — pgvector 컬럼은 생성 시 차원이 고정되므로(스펙 020
함정3) 이 값이 단일 출처다. `CREATE EXTENSION vector`를 멱등 보장한다.

가역: downgrade는 3종 테이블을 제거하고 vector_tables(원형)를 복구한다(데이터는 복원 불가 —
mock 시드였음).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from api.models import RAG_EMBED_DIMS

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 죽은 mock 카탈로그 제거 — collections로 재생.
    op.drop_table("vector_tables")

    op.create_table(
        "collections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding_model_id", sa.UUID(), nullable=False),
        sa.Column("dims", sa.Integer(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="empty"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        # 임베딩 모델 삭제 차단 — 컬렉션이 매달려 있으면 모델을 못 지운다(차원 정합 보장).
        sa.ForeignKeyConstraint(["embedding_model_id"], ["models.id"], ondelete="RESTRICT"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=400), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="parsing"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_documents_collection_id", "documents", ["collection_id"])

    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", Vector(RAG_EMBED_DIMS), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_rag_chunks_document_id", "rag_chunks", ["document_id"])
    op.create_index("ix_rag_chunks_collection_id", "rag_chunks", ["collection_id"])
    # HNSW cosine 인덱스 — 037 retrieval의 근사 최근접 검색용(코사인 거리).
    op.create_index(
        "ix_rag_chunks_embedding_hnsw",
        "rag_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_embedding_hnsw", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_collection_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_document_id", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_index("ix_documents_collection_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("collections")

    # vector_tables(원형) 복구 — 데이터는 복원 불가(mock 시드였음).
    op.create_table(
        "vector_tables",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("dims", sa.Integer(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
