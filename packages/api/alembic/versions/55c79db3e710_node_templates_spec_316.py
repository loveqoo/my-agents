"""node_templates (스펙 316 — 노드 라이브러리: 등록 노드 + 버전 고정 참조)

Revision ID: 55c79db3e710
Revises: f312a1b2c3d4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "55c79db3e710"
down_revision = "f312a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 노드 라이브러리 — (name, version) 유니크, 발행 후 불변(수정=새 버전 발행).
    # kind=code는 스펙 317(코드 노드) 예약 — 본 스펙은 config만 저장한다.
    op.create_table(
        "node_templates",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(20), nullable=False, server_default="config"),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_node_templates_name_version"),
    )


def downgrade() -> None:
    op.drop_table("node_templates")
