"""죽은 '단기(세션)' memory_types 행 제거(스펙 387 후속).

스펙 387이 라이브 행을 삭제했으나, c1d2e3f4a5b6(카탈로그 재정렬)이 **데이터 시드로 이 행을
INSERT**해 fresh DB(초기화·처녀 빌드)마다 부활했다(2026-07-17 실측 — DB 초기화 후 드롭다운 재등장).
기존 리비전은 불변으로 두고(수정 시 기존 DB와 비결정 어긋남) 체인 끝에서 DELETE — fresh/기존 DB의
최종 상태를 동일하게 만든다. 이 행은 실동작이 없는 죽은 옵션(memory_enabled는 '장기 기억 (mem0)'
멤버십만 판정)이며, 진짜 단기 기억은 historyDepth 컨트롤이 소유한다(스펙 270).

Revision ID: 40079d14052f
Revises: 3b0c41417794
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "40079d14052f"
down_revision: Union[str, Sequence[str], None] = "3b0c41417794"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEAD = "단기(세션)"


def upgrade() -> None:
    # 멱등 DELETE — 이미 없으면(387이 지운 라이브 DB) 0행. 참조 무결성: 이 이름을 참조하는 config는
    # 이미 조용한 no-op이었고(스펙 387), 저장 검증(assert_memory_names_exist)이 재유입을 막는다.
    op.execute("DELETE FROM memory_types WHERE name = '단기(세션)'")


def downgrade() -> None:
    # c1d2e3f4a5b6의 새 카탈로그 상태로 복원(다운그레이드 대칭).
    # created_by/updated_by: 감사 컬럼 NOT NULL(스펙 343) — 누락 시 downgrade가 NotNullViolation
    # (verify_343 왕복 실측). 시드와 동일하게 'system' 스탬프.
    op.execute(
        "INSERT INTO memory_types (id, key, name, scope, body, created_by, updated_by) "
        "SELECT gen_random_uuid(), '단기(세션)', '단기(세션)', 'In-context · mem0 아님', "
        "'현재 세션의 인-컨텍스트 윈도우(historyDepth) — 최근 N턴만 모델에 전달하는 컨텍스트 절단입니다. "
        "mem0 저장소가 아니며 세션이 끝나면 사라집니다.', 'system', 'system' "
        "WHERE NOT EXISTS (SELECT 1 FROM memory_types WHERE name = '단기(세션)')"
    )
