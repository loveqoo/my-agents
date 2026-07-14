"""마이그레이션 시드 행의 감사 actor를 system으로 정정 (스펙 345).

providers/models 시드는 **마이그레이션**이 raw SQL로 넣는다(a1b2c3d4e5f6·c9d0e1f2a3b4·f4a5b6c7d8e9).
이들은 343(감사 컬럼)보다 먼저 돌아 컬럼이 없었고, 343의 백필이 `unknown`(=감사 도입 이전 행)으로
채웠다 — **갓 만든 DB인데 "도입 이전"이라고 찍히는 거짓말**. 마이그레이션이 만든 행의 주체는
알 수 있다: `system`.

**일괄 unknown→system 금지**(스펙 345 설계): 다른 환경의 unknown에는 343 이전에 관리자가 만든
진짜 레거시 행이 섞여 있다. 아는 것(시드 행)만 정확히 지목해 정정한다.

Revision ID: b8e4d2c7a915
Revises: a7f3c9e21b4d
"""

from alembic import op

revision: str = "b8e4d2c7a915"
down_revision: str | None = "a7f3c9e21b4d"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # provider — 시드가 만든 Mock LLM(kind=mock)만.
    op.execute(
        "UPDATE providers SET created_by = 'system', updated_by = 'system' "
        "WHERE kind = 'mock' AND name = 'Mock LLM' AND created_by = 'unknown'"
    )
    # models — 시드 2행(model_id로 식별). 관리자가 추가한 동명 모델을 건드리지 않도록 model_id까지 본다.
    op.execute(
        "UPDATE models SET created_by = 'system', updated_by = 'system' "
        "WHERE created_by = 'unknown' AND model_id IN ('mock-chat', 'mock-embed') "
        "AND provider_id IN (SELECT id FROM providers WHERE kind = 'mock')"
    )
    # allowed_hosts — 마이그레이션(d0e1f2a3b4c5)이 심는 기본 로컬 호스트만. 관리자가 추가한 호스트는
    # 손대지 않는다(그건 사람이 만든 행 — unknown으로 남는 게 정직).
    op.execute(
        "UPDATE allowed_hosts SET created_by = 'system', updated_by = 'system' "
        "WHERE created_by = 'unknown' AND host IN ('127.0.0.1', 'localhost')"
    )
    # memory_types — 시스템 카탈로그(읽기 전용 시드, 생성 라우트 없음)라 전 행이 마이그레이션 산물.
    op.execute(
        "UPDATE memory_types SET created_by = 'system', updated_by = 'system' "
        "WHERE created_by = 'unknown'"
    )


def downgrade() -> None:
    # 되돌림 = 시드 행을 다시 unknown으로(343 백필 직후 상태).
    op.execute(
        "UPDATE memory_types SET created_by = 'unknown', updated_by = 'unknown' "
        "WHERE created_by = 'system'"
    )
    op.execute(
        "UPDATE allowed_hosts SET created_by = 'unknown', updated_by = 'unknown' "
        "WHERE created_by = 'system' AND host IN ('127.0.0.1', 'localhost')"
    )
    op.execute(
        "UPDATE providers SET created_by = 'unknown', updated_by = 'unknown' "
        "WHERE kind = 'mock' AND name = 'Mock LLM' AND created_by = 'system'"
    )
    op.execute(
        "UPDATE models SET created_by = 'unknown', updated_by = 'unknown' "
        "WHERE created_by = 'system' AND model_id IN ('mock-chat', 'mock-embed') "
        "AND provider_id IN (SELECT id FROM providers WHERE kind = 'mock')"
    )
