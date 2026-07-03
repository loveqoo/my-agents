"""kind당 기본 모델 1개를 DB 부분 유니크 인덱스로 강제 (spec 150)

동시 기본 지정 레이스(codex 150 High)에서 READ COMMITTED 하 두 트랜잭션이 서로의 미커밋 기본을
못 보고 각자 커밋해 기본이 2개가 되는 경로를 DB 불변식으로 봉인. 경합 패자는 IntegrityError →
라우트가 409로 접는다. 기존 데이터는 kind당 정확히 1개(시드·_clear_other_defaults 유지)라 안전.

Revision ID: a1b2c3d4e5f7
Revises: f0a1b2c3d4e5
Create Date: 2026-07-03 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_models_default_per_kind ON models (kind) WHERE is_default"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_models_default_per_kind")
