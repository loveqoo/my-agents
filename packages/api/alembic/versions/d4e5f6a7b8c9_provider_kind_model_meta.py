"""provider kind/description + model meta (spec 047)

프로바이더·모델 통합 + models.dev. Provider에 kind(local/mock/remote)·description
추가(라벨 혼란 #6), ModelConfig에 meta(JSONB) 추가(models.dev 카탈로그 파생 메타 #7).
손으로 작성(autogenerate 회피 — learning 033: autogenerate가 pgvector/외부 테이블 drop).
기존 행은 server_default로 백필(kind=remote, description="", meta={}). 무중단.

Revision ID: d4e5f6a7b8c9
Revises: c8d9e0f1a2b3
Create Date: 2026-06-28 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="remote"),
    )
    op.add_column(
        "providers",
        sa.Column("description", sa.String(length=400), nullable=False, server_default=""),
    )
    op.add_column(
        "models",
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("models", "meta")
    op.drop_column("providers", "description")
    op.drop_column("providers", "kind")
