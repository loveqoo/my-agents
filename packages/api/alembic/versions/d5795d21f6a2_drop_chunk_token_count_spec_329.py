"""chunks.token_count DROP (스펙 329 — 죽은 영역 감사 324 잔여 제거)

Revision ID: d5795d21f6a2
Revises: 55c79db3e710

쓰기 2곳(rag.py 인제스트·재인덱싱)만 있고 읽기 0인 write-only 컬럼(감사 324 유력분, 사용자 결정
2026-07-13 DROP). 값은 파생값(len(text.split()))이라 소실 무해 — downgrade는 컬럼을 default 0으로
재생성한다(**lossy**: 기존 값 미복원, 필요 시 파생 재계산).
"""

import sqlalchemy as sa
from alembic import op

revision = "d5795d21f6a2"
down_revision = "55c79db3e710"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("rag_chunks", "token_count")


def downgrade() -> None:
    op.add_column(
        "rag_chunks",
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
    )
