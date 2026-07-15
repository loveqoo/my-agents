"""rename persona to prompt spec 365

Revision ID: ee861d878e95
Revises: 41c4b95512e6
Create Date: 2026-07-15 17:39:42.597243

스펙 365 — 페르소나 → 프롬프트 완전 개명(구조만). DB 초기화로 데이터 무시 → JSONB config 변환 없음
(새 시드가 prompts 테이블·config.prompt로 바로 쓴다). 처녀 빌드는 전 체인(초기: personas 생성 →
이 리비전: prompts로 rename)으로 정합 스키마를 만든다(append-only — 과거 마이그레이션 미편집).
- personas 테이블 → prompts(제약 personas_pkey/personas_name_key도 위생상 rename).
- agents.persona 컬럼(해석 프롬프트 본문) → agents.prompt.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee861d878e95"
down_revision: Union[str, Sequence[str], None] = "41c4b95512e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("personas", "prompts")
    op.execute("ALTER TABLE prompts RENAME CONSTRAINT personas_pkey TO prompts_pkey")
    op.execute("ALTER TABLE prompts RENAME CONSTRAINT personas_name_key TO prompts_name_key")
    op.alter_column("agents", "persona", new_column_name="prompt")


def downgrade() -> None:
    op.alter_column("agents", "prompt", new_column_name="persona")
    op.execute("ALTER TABLE prompts RENAME CONSTRAINT prompts_name_key TO personas_name_key")
    op.execute("ALTER TABLE prompts RENAME CONSTRAINT prompts_pkey TO personas_pkey")
    op.rename_table("prompts", "personas")
