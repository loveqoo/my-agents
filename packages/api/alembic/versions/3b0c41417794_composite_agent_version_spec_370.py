"""composite agent version spec 370

Revision ID: 3b0c41417794
Revises: f79412647c2d
Create Date: 2026-07-16

스펙 370 — 복합 에이전트 버전: agent_versions에 ever_opened(오픈 이력)+pins(블록 버전 못박기),
status(draft/active/archived) 상태기계 폐기. 백필: ever_opened = (status != 'draft') — 오픈됐던
버전만 불변 보호. pins 백필은 앱 부트 ensure_agent_pins(멱등 — freeze 로직을 SQL로 중복 정의하지
않음, 369 패턴). autogenerate의 런타임 소유 테이블 drop·무관 churn은 트림(learning 364).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3b0c41417794'
down_revision: Union[str, Sequence[str], None] = 'f79412647c2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column("ever_opened", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "agent_versions",
        sa.Column(
            "pins", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    # 백필: 한 번이라도 서빙됐던 버전(active/archived) = 오픈 이력. draft만 스크래치로 남는다.
    op.execute("UPDATE agent_versions SET ever_opened = (status != 'draft')")
    op.drop_column("agent_versions", "status")


def downgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
    )
    # 역백필(손실 있는 근사): 오픈 이력=archived, 스크래치=draft. active는 포인터가 알므로 복원 불가.
    op.execute(
        "UPDATE agent_versions SET status = CASE WHEN ever_opened THEN 'archived' ELSE 'draft' END"
    )
    op.drop_column("agent_versions", "pins")
    op.drop_column("agent_versions", "ever_opened")
