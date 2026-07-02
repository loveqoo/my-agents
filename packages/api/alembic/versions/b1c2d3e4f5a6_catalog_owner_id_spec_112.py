"""add owner_id to agents/mcp_servers/collections (spec 112 — 공유 카탈로그 소유권)

브로커 능력 인가를 kind 단위에서 **자원 소유자 단위**로 좁힌다(codex 100/101 [P1] #1/#2 봉합).
Agent·McpServer·Collection에 owner_id(요청 주체 auth User UUID str) 추가. **기존 행은 NULL로 남아
admin 전용으로 fail-closed**(소급 채움 없음 — learning 070: 레거시 행이 일반 유저에게 열리면 안 된다.
오늘 카탈로그는 admin 저작·admin/superuser만 브로커 사용이라 member 무회귀). 신규 생성 시 스탬프.
owner 스코프 조회를 위해 인덱스 추가.

Revision ID: b1c2d3e4f5a6
Revises: a3b4c5d6e7f8
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("agents", "mcp_servers", "collections")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("owner_id", sa.String(length=80), nullable=True))
        op.create_index(f"ix_{t}_owner_id", t, ["owner_id"])


def downgrade() -> None:
    for t in _TABLES:
        op.drop_index(f"ix_{t}_owner_id", table_name=t)
        op.drop_column(t, "owner_id")
