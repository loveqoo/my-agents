"""체크포인트 스윕 노브 (스펙 346).

batch_config에 `checkpoint_ttl_hours`(기본 24) · `checkpoint_cleanup_cron`(기본 매시)를 추가한다.
다른 배치 노브는 기본 NULL(비활성)이지만 이 둘은 기본값을 넣는다 — 청소를 안 하면 체크포인트가
무한 누적되는 게 기본 동작이라, 여기선 "안 하기"가 보수적인 쪽이 아니다(스펙 346). 파괴 반경은
재개 근거(체크포인트)에 한정되고 24h 문턱이 진행 중 턴을 지킨다. 끄려면 cron을 NULL로.

기존 행(싱글톤)에도 같은 기본값을 채운다 — 컬럼만 추가하면 이미 배포된 DB는 NULL=비활성으로 남아
청소가 조용히 안 돈다.

Revision ID: 1323fa51561d
Revises: b8e4d2c7a915
"""

import sqlalchemy as sa
from alembic import op

revision: str = "1323fa51561d"
down_revision: str | None = "b8e4d2c7a915"
branch_labels: str | None = None
depends_on: str | None = None

_DEFAULT_TTL_HOURS = 24
_DEFAULT_CRON = "0 * * * *"  # 매시 정각 — TTL(24h)보다 촘촘해야 고아가 문턱 직후 회수된다


def upgrade() -> None:
    op.add_column("batch_config", sa.Column("checkpoint_ttl_hours", sa.Integer(), nullable=True))
    op.add_column(
        "batch_config", sa.Column("checkpoint_cleanup_cron", sa.String(length=120), nullable=True)
    )
    op.execute(
        "UPDATE batch_config SET checkpoint_ttl_hours = "
        f"{_DEFAULT_TTL_HOURS}, checkpoint_cleanup_cron = '{_DEFAULT_CRON}' "
        "WHERE checkpoint_ttl_hours IS NULL AND checkpoint_cleanup_cron IS NULL"
    )


def downgrade() -> None:
    op.drop_column("batch_config", "checkpoint_cleanup_cron")
    op.drop_column("batch_config", "checkpoint_ttl_hours")
