"""message feedback (spec 209)

응답 피드백(👍/👎+이유) 저장 — 평가 케이스 수확의 원천(스펙 209 Phase 1). assistant 메시지에 대한
사용자별 1건(재클릭=upsert). message/session 삭제 시 CASCADE.

리비전 ID는 고유 hex(손수 순번 금지 — spec 슬롯 충돌 silent overwrite 방지, learning 157).
Revises=현재 단일 head c193a1b2c3d4(spec 193).

Revision ID: f209a1b2c3d4
Revises: c193a1b2c3d4
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "f209a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "c193a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_pk",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_pk",
            UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_message_feedback_message_pk", "message_feedback", ["message_pk"])
    op.create_index("ix_message_feedback_session_pk", "message_feedback", ["session_pk"])
    op.create_index("ix_message_feedback_created_by", "message_feedback", ["created_by"])
    # 사용자당 메시지당 1건(upsert 키)
    op.create_index(
        "uq_message_feedback_msg_user",
        "message_feedback",
        ["message_pk", "created_by"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_message_feedback_msg_user", table_name="message_feedback")
    op.drop_index("ix_message_feedback_created_by", table_name="message_feedback")
    op.drop_index("ix_message_feedback_session_pk", table_name="message_feedback")
    op.drop_index("ix_message_feedback_message_pk", table_name="message_feedback")
    op.drop_table("message_feedback")
