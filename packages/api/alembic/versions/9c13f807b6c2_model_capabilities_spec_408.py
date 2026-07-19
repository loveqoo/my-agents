"""model capabilities spec 408

Revision ID: 9c13f807b6c2
Revises: 7218f9ea87d7
Create Date: 2026-07-19 22:54:23.286009

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c13f807b6c2"
down_revision: str | Sequence[str] | None = "7218f9ea87d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 모델 능력 선언(스펙 408) — 2층 원칙의 능력 층. 기존 행은 스트리밍 지원으로 간주(현행 동작 보존:
    # 지금까지 전부 스트리밍 호출로 동작해 왔으므로 true가 사실 기록이다).
    op.add_column(
        "models",
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(
                '\'{"streaming": true, "thinking": false, "vision": false}\'::jsonb'
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("models", "capabilities")
