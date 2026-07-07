"""feedback harvested_case link (spec 209 Phase 2)

message_feedback에 harvested_case_pk(→eval_cases) 추가 — 피드백을 평가 케이스로 수확한 링크.
NULL=미수확. 케이스 삭제 시 SET NULL(재수확 가능). 재수확 방지·추적.

리비전 ID는 고유 hex(손수 순번 금지 — learning 157). Revises=현재 단일 head f209a1b2c3d4(spec 209 P1).

Revision ID: f210a1b2c3d4
Revises: f209a1b2c3d4
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "f210a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "f209a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_feedback",
        sa.Column(
            "harvested_case_pk",
            UUID(as_uuid=True),
            sa.ForeignKey("eval_cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_message_feedback_harvested_case_pk", "message_feedback", ["harvested_case_pk"]
    )
    # 수확 문제집↔에이전트 링크(idempotent 수확) — eval_datasets.source_agent_pk.
    op.add_column(
        "eval_datasets",
        sa.Column(
            "source_agent_pk",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_eval_datasets_source_agent_pk", "eval_datasets", ["source_agent_pk"]
    )


def downgrade() -> None:
    op.drop_index("ix_eval_datasets_source_agent_pk", table_name="eval_datasets")
    op.drop_column("eval_datasets", "source_agent_pk")
    op.drop_index("ix_message_feedback_harvested_case_pk", table_name="message_feedback")
    op.drop_column("message_feedback", "harvested_case_pk")
