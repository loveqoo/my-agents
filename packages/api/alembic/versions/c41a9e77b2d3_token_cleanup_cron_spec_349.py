"""만료 토큰 회수 cron 노브 (스펙 349).

로그인마다 accesstoken 1행이 쌓이는데 지우는 코드가 로그아웃뿐이었다(만료 후에도 영구 잔류).
배치 잡 `token-cleanup`의 스케줄을 담을 컬럼. 기본 매일 04:00 — 안 치우면 무한 누적이 기본
동작이라 "안 하기"가 보수적인 쪽이 아니다(스펙 346과 같은 논리). 끄려면 NULL.

Revision ID: c41a9e77b2d3
Revises: 1323fa51561d
"""

import sqlalchemy as sa
from alembic import op

revision: str = "c41a9e77b2d3"
down_revision: str | None = "1323fa51561d"
branch_labels: str | None = None
depends_on: str | None = None

_DEFAULT_CRON = "0 4 * * *"


def upgrade() -> None:
    op.add_column("batch_config", sa.Column("token_cleanup_cron", sa.String(length=120), nullable=True))
    op.execute(
        f"UPDATE batch_config SET token_cleanup_cron = '{_DEFAULT_CRON}' WHERE token_cleanup_cron IS NULL"
    )


def downgrade() -> None:
    op.drop_column("batch_config", "token_cleanup_cron")
