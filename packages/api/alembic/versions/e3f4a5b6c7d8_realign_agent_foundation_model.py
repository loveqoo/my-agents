"""realign agent foundation model to registered models (spec 023)

에이전트들의 model이 레지스트리에 없는 가상명(claude-*/gpt-*)을 가리켜 매 실행 시
기본 chat 모델로 폴백하던 것을, 등록된 기본 chat 모델로 정정한다. agents.model 컬럼과
agents/agent_versions의 config.model(JSONB)을 모두 갱신한다. 가상명을 하드코딩하지 않고
models 테이블에서 기본 chat 모델을 동적으로 골라 적용 — 기본 chat 모델이 없으면(빈 DB)
no-op 하고 seed.py가 올바른 값으로 채운다.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-25 00:00:00.000000

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # 등록된 chat 모델명 집합 + 기본(is_default) chat 모델.
    chat_names = {
        r[0] for r in conn.execute(
            sa.text("SELECT name FROM models WHERE kind = 'chat'")
        ).fetchall()
    }
    default_chat = conn.execute(
        sa.text(
            "SELECT name FROM models WHERE kind = 'chat' AND is_default = true "
            "ORDER BY name LIMIT 1"
        )
    ).scalar()
    if not default_chat:
        # 등록된 기본 chat 모델 없음(빈 DB 등) → 손대지 않는다. seed가 올바르게 채움.
        return

    # agents: model 컬럼과 config.model을 각각 등록명으로 정정.
    # config.model은 키가 있고 미등록일 때만 손댄다(키 부재 시 추가하지 않음 —
    # agent_versions와 동일 기준, 불필요한 데이터 변형 방지).
    for rid, model, config in conn.execute(
        sa.text("SELECT id, model, config FROM agents")
    ).fetchall():
        cfg = config or {}
        new_model = model if model in chat_names else default_chat
        cfg_model = cfg.get("model")
        fix_cfg = "model" in cfg and cfg_model not in chat_names
        if new_model == model and not fix_cfg:
            continue
        newcfg = {**cfg, "model": default_chat} if fix_cfg else cfg
        conn.execute(
            sa.text(
                "UPDATE agents SET model = :m, config = CAST(:c AS jsonb) WHERE id = :id"
            ),
            {"m": new_model, "c": json.dumps(newcfg, ensure_ascii=False), "id": rid},
        )

    # agent_versions: config.model만 정정(model 키가 있고 미등록일 때).
    for rid, config in conn.execute(
        sa.text("SELECT id, config FROM agent_versions")
    ).fetchall():
        cfg = config or {}
        m = cfg.get("model")
        if m is None or m in chat_names:
            continue
        newcfg = {**cfg, "model": default_chat}
        conn.execute(
            sa.text(
                "UPDATE agent_versions SET config = CAST(:c AS jsonb) WHERE id = :id"
            ),
            {"c": json.dumps(newcfg, ensure_ascii=False), "id": rid},
        )


def downgrade() -> None:
    # 가상 모델명은 복원 불가(비가역 데이터 정정) — no-op.
    pass
