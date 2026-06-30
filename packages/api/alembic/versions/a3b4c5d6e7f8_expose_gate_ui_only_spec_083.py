"""A2A 노출은 source=ui만 — 기존 non-ui stale exposed.a2a 청소 (스펙 083)

`exposed.a2a=True`는 로컬(source=ui) 에이전트를 우리 A2A 서버로 여는 플래그인데(스펙 061),
A2A 서버 게이트(a2a_server._load_exposed_ui_agent)는 이미 source==ui로 fail-closed다. 그러나
`/expose` 입구·시드가 source를 안 봐서 code/external에 True가 박힌 "겉도는 죽은 상태"가 있었다
(seed.py의 Doc Translator 등). 083이 입구(400 거부)·UI·시드를 정렬하면서, **기존 DB의 stale
true도 false로 내려 불변식 `exposed.a2a=true ⟹ source=ui`를 데이터에 성립**시킨다.

멱등: 이미 false거나 source=ui면 매치 안 함. downgrade는 no-op(과거 잘못된 상태 복원은 의미 없음).

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-06-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # non-ui(code·external)의 stale 노출 플래그를 끈다.
    # jsonb_set(.., create_missing=true)로 a2a 키만 false 세팅 — 형제 키 보존(통째 교체 금지).
    op.execute(
        """
        UPDATE agents
        SET exposed = jsonb_set(COALESCE(exposed, '{}'::jsonb), '{a2a}', 'false'::jsonb, true)
        WHERE source <> 'ui' AND (exposed ->> 'a2a') = 'true'
        """
    )


def downgrade() -> None:
    # 과거 dead state(non-ui+true)로 되돌리는 것은 의미 없음 — no-op.
    pass
