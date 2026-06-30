"""session 읽기 저장계층 타이밍 봉합 — owner-선두 복합 인덱스 (스펙 073, 070 P2)

070이 세션 읽기 게이트를 앱(파이썬) 계층에서 단일화했으나, `session_id` 단독 unique 인덱스가 남아
member 쿼리 `WHERE session_id=:id AND user_id=:own`에서 Postgres가 타인-존재행을 heap-fetch한 뒤
거부 vs 부재행은 인덱스 미스 → 저장계층에 타인-존재 vs 부재 buffer 델타가 잔존했다(070 §적대 [P2]).

owner를 선두 컬럼으로 둔 복합 인덱스를 추가해, 타인 행이 `(내_user_id, 그_session_id)` 조합으로
인덱스 진입 단계에서 부재행과 동일하게 미스되게 한다(타인 행은 *타인의 user_id* 아래 있음):
  - (user_id, session_id)            : 읽기 게이트(_get_session_or_404 member 경로)
  - (user_id, agent_pk, session_id)  : chat resume member 경로

session_id 단독 unique는 전역 uniqueness 보장(get-or-create flush 의존)으로 *유지*한다 — 복합은
조회 경로 단일화용(unique=False). 플래너가 실제로 복합을 선택하는지는 EXPLAIN으로 측정해야 봉합이
완성된다(verify_073_explain). 가역: downgrade는 두 인덱스를 제거(데이터 무손실).

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # if_not_exists: 재실행·부분드리프트(한 인덱스만 선존재) 시 실패 대신 수렴(멱등, 스펙 §D1).
    op.create_index(
        op.f("ix_sessions_user_id_session_id"),
        "sessions",
        ["user_id", "session_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_sessions_user_id_agent_pk_session_id"),
        "sessions",
        ["user_id", "agent_pk", "session_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sessions_user_id_agent_pk_session_id"), table_name="sessions", if_exists=True
    )
    op.drop_index(op.f("ix_sessions_user_id_session_id"), table_name="sessions", if_exists=True)
