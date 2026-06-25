"""add mock-llm registry chat model (spec 024)

라이브 MLX 없이 에이전트를 결정적으로 돌릴 수 있도록 `mock-llm` chat 모델을 레지스트리에
등록한다. 이미 시드된 라이브 DB는 seed_if_empty가 다시 돌지 않으므로(빈 DB에서만 시드),
이 데이터 마이그레이션으로 멱등 삽입한다(이름 존재 시 skip). is_default는 손대지 않는다
(실 MLX가 기본, mock은 에이전트가 명시 선택해야 발동).

api_key는 평문 'sk-noauth' — mock 엔드포인트는 인증을 검증하지 않고, crypto.decrypt는
레거시 평문을 그대로 반환하므로 키 의존 없이 안전하다.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-25 00:00:00.000000

"""
import os
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM models WHERE name = 'mock-llm'")
    ).scalar()
    if exists:
        # 이미 있음(빈 DB에서 seed가 채웠거나 재실행) → 멱등 skip.
        return
    base = os.environ.get("MOCK_LLM_BASE_URL", "http://127.0.0.1:8000/_remote/v1")
    conn.execute(
        sa.text(
            "INSERT INTO models "
            "(id, name, provider, base_url, api_key, model_id, kind, is_default, params) "
            "VALUES (:id, 'mock-llm', 'openai-compatible', :base, 'sk-noauth', "
            "'mock-chat', 'chat', false, CAST('{}' AS jsonb))"
        ),
        {"id": str(uuid.uuid4()), "base": base},
    )


def downgrade() -> None:
    # 가역 — mock-llm 행 제거. (이 모델을 참조하는 에이전트가 있으면 런타임은 기본 chat으로 폴백.)
    # `mock-llm` 이름은 seed/이 마이그레이션이 **소유**하는 데모 데이터다 — upgrade가 멱등 skip한
    # 경우(이미 존재)에도 downgrade는 무조건 삭제한다. 이름 소유 정책이라 외부 선삽입 행은 가정하지
    # 않는다(codex P2-2 수용). 엄밀한 역연산이 필요하면 삽입 마커가 필요하나, 데모 데이터엔 과함.
    op.get_bind().execute(sa.text("DELETE FROM models WHERE name = 'mock-llm'"))
