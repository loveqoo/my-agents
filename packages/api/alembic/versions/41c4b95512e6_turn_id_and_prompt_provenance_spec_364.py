"""turn_id and prompt provenance spec 364

Revision ID: 41c4b95512e6
Revises: f74d0e36a9c2
Create Date: 2026-07-15 17:15:00.397654

스펙 364 — 대화 이력(messages)에 턴 id + 프롬프트(페르소나) 출처 컬럼 추가.
autogenerate가 끌어온 무관 드리프트(런타임 소유 테이블 checkpoints/mem0_memories/casbin_rule 삭제,
agents·message_feedback·approvals·rag_chunks 인덱스 변경)는 전부 제거 — 그 테이블/인덱스는 langgraph·
mem0·casbin이 런타임에 만들거나 의도된 기존 상태라 우리 모델 metadata 밖이다(스펙 329 결: alembic이
스키마 단일 진실이나, 런타임 소유 객체는 그 대상 아님). 이 마이그레이션은 messages 3컬럼+2인덱스만 손댄다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "41c4b95512e6"
down_revision: Union[str, Sequence[str], None] = "f74d0e36a9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("turn_id", sa.String(length=200), nullable=True))
    op.add_column("messages", sa.Column("prompt_id", sa.String(length=80), nullable=True))
    op.add_column("messages", sa.Column("prompt_name", sa.String(length=200), nullable=True))
    op.create_index(op.f("ix_messages_turn_id"), "messages", ["turn_id"], unique=False)
    op.create_index(op.f("ix_messages_prompt_id"), "messages", ["prompt_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_prompt_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_turn_id"), table_name="messages")
    op.drop_column("messages", "prompt_name")
    op.drop_column("messages", "prompt_id")
    op.drop_column("messages", "turn_id")
