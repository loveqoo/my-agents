"""유저 자산 상한 — 메시지 보존 180일 기본 ON (스펙 429).

살아있는 유저 메시지(세션)는 회수 캠페인(346~352)이 안 지워 무한 증가하던 축이다. session-cleanup
배치의 보존정책(session_retention_days·cron)이 기본 OFF(NULL)였던 걸 **기본 180일 ON**으로(구남님 승인).

기존 싱글톤엔 **NULL인 필드만** 기본값으로 채운다(COALESCE — 사용자가 이미 커스텀한 값은 보존).
신규 DB의 싱글톤은 모델 기본값(models/batch.py: default=180)으로 켜져 생성된다.
(유저 기억 상한 1000은 코드 관문 memory.add() 축출이라 스키마 변경 없음.)

Revision ID: 9b5f74121771
Revises: 9c13f807b6c2
"""

from alembic import op

revision: str = "9b5f74121771"
down_revision: str | None = "9c13f807b6c2"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 필드별 preserve: NULL만 기본값으로(사용자 커스텀 유지). 싱글톤 1행 전제.
    op.execute(
        "UPDATE batch_config SET "
        "session_retention_days = COALESCE(session_retention_days, 180), "
        "session_cleanup_cron = COALESCE(session_cleanup_cron, '0 3 * * *')"
    )


def downgrade() -> None:
    # no-op(정직) — 값만으로 "이 migration이 켠 기본값(180·cron)"과 "사용자가 우연히 같은 값을 커스텀한
    # 것"을 구분할 수 없어(codex 429), NULL로 되돌리면 사용자 커스텀을 파괴한다. 스키마 변경도 없어
    # 되돌릴 구조가 없다. 보존정책 비활성화는 값 되돌림이 아니라 관리자가 설정에서 조정한다.
    pass
