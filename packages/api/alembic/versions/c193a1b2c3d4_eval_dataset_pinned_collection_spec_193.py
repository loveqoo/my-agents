"""eval dataset pinned collection (spec 193)

RAG 문제집의 대상 컬렉션을 문제집에 고정(실행 시 재선택 제거). nullable — agent 문제집·구버전 rag
문제집은 NULL(첫 실행 시 lazy 저장). collections 삭제 시 SET NULL(문제집 보존, 연결만 끊김).

리비전 ID는 고유 hex(손수 순번 금지 — spec 슬롯 충돌 silent overwrite 방지, learning 157).
Revises=현재 단일 head a181c2d3e4f5(spec 181).

Revision ID: c193a1b2c3d4
Revises: a181c2d3e4f5
Create Date: 2026-07-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c193a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "a181c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "eval_datasets",
        sa.Column(
            "collection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("collections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_eval_datasets_collection_id", "eval_datasets", ["collection_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_datasets_collection_id", table_name="eval_datasets")
    op.drop_column("eval_datasets", "collection_id")
