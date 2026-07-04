"""approval approver (spec 177 P2)

도구 승인 정책의 승인자를 Approval에 스탬프 — "admin"=관리자만 resolve, "self"=요청 소유자 본인.
NULL = 레거시·메모리·A2A 승인(이 마이그레이션 이전 행 포함) → _may_resolve가 Casbin
can_self_approve 폴백(무회귀). MCP 도구 승인만 리졸버가 값을 박는다.

Revision ID: a1b2c3d4e5f7
Revises: f6a7b8c9d1e2
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable — 기존 pending/결재 행은 NULL(Casbin 폴백, 하위호환). 신규 MCP 도구 승인만 값이 박힌다.
    op.add_column("approvals", sa.Column("approver", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "approver")
