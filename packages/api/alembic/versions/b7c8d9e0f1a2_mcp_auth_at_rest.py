"""mcp auth at-rest: widen mcp_servers.auth for Fernet ciphertext (spec 054 F)

기존 `auth`(평문 토큰, String 120)를 암호화 크리덴셜로 승격한다 — Fernet 토큰은
base64url로 평문보다 길어 120을 넘으므로 400으로 확장. 의미 전환: 저장은 암호문,
응답은 마스킹(`••••`), 런타임은 복호화 → Bearer 헤더(provider.api_key와 동형).
기존 평문 행은 crypto.decrypt의 레거시 passthrough로 호환(시드 G에서 재정합).

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-06-28 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "mcp_servers",
        "auth",
        existing_type=sa.String(length=120),
        type_=sa.String(length=400),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "mcp_servers",
        "auth",
        existing_type=sa.String(length=400),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
