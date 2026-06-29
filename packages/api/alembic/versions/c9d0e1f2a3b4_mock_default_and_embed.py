"""mock-llm을 기본 chat으로 + mock-embed 임베딩 보장 (spec 059)

정상 alembic 경로의 fresh 설치 결함을 고친다: f4a5(mock-llm INSERT)+a1b2c3(provider 정규화)가
Provider 행을 먼저 만들어, seed_if_empty의 Provider 블록이 `_empty(Provider)=False`로 **스킵**된다.
그 결과 head까지 올린 fresh DB에는 기본 chat 모델도 임베딩 모델도 없고, 시드 에이전트가 없는 모델을
가리키며, 컬렉션 시드가 빈 임베딩 목록에 접근한다. 이 마이그레이션이 alembic 경로의 기본값을
**작동하는 Mock 기본**으로 세운다(create_all 폴백 경로는 seed.py가 동일 상태를 만든다 — 두 경로 수렴).

원칙(스펙 059):
- **기존 설치 클로버 금지** — chat 기본이 이미 있으면 mock 승격 안 함(의도적 실모델 default 보존).
- **멱등** — mock-embed는 이름 존재 시 skip. 재실행 안전.
- mock-llm이 없으면(예외적 옛 상태) 손대지 않는다 — seed/다른 마이그레이션 책임.

api_key·평문 정책은 f4a5와 동일(mock 엔드포인트는 인증 미검증).

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-06-29 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1) mock-llm chat 모델과 그 provider_id 확보(a1b2c3가 정규화해 둔 provider).
    row = conn.execute(
        sa.text("SELECT id, provider_id FROM models WHERE name = 'mock-llm' AND kind = 'chat'")
    ).fetchone()
    if row is None:
        # mock-llm이 없는 예외적 상태 — 이 마이그레이션은 손대지 않는다.
        return
    chat_pk, provider_id = row[0], row[1]

    # 2) provider를 'Mock LLM'/kind=mock으로 정규화 → 두 부팅 경로의 표시 이름까지 수렴.
    #    (alembic 경로의 provider 이름은 a1b2c3가 base_url netloc에서 파생하므로 'Mock LLM'이 아니다.)
    #    이미 다른 행이 'Mock LLM' 이름을 점유하면 unique 충돌 회피 — kind/description만 맞춘다.
    name_taken = conn.execute(
        sa.text("SELECT 1 FROM providers WHERE name = 'Mock LLM' AND id != :pid"),
        {"pid": provider_id},
    ).scalar()
    if name_taken:
        conn.execute(
            sa.text(
                "UPDATE providers SET kind = 'mock', "
                "description = '라이브 없이 결정적 동작용 내장 목(스펙 024) — 기본 provider(059)' "
                "WHERE id = :pid"
            ),
            {"pid": provider_id},
        )
    else:
        conn.execute(
            sa.text(
                "UPDATE providers SET name = 'Mock LLM', kind = 'mock', "
                "description = '라이브 없이 결정적 동작용 내장 목(스펙 024) — 기본 provider(059)' "
                "WHERE id = :pid"
            ),
            {"pid": provider_id},
        )

    # 3) chat 기본 모델이 하나도 없을 때만 mock-llm을 default로 승격(기존 실모델 default 보존).
    has_default_chat = conn.execute(
        sa.text("SELECT 1 FROM models WHERE kind = 'chat' AND is_default = true LIMIT 1")
    ).scalar()
    if not has_default_chat:
        conn.execute(
            sa.text("UPDATE models SET is_default = true WHERE id = :id"), {"id": chat_pk}
        )

    # 4) mock-embed 임베딩 모델 멱등 삽입(이름 존재 시 skip). 임베딩 기본이 없으면 default로.
    #    → 임베딩 모델 부재(컬렉션 바인딩 크래시)·RAG 게이트(스펙 048) 안전.
    embed_exists = conn.execute(
        sa.text("SELECT 1 FROM models WHERE name = 'mock-embed'")
    ).scalar()
    if not embed_exists:
        has_default_embed = conn.execute(
            sa.text("SELECT 1 FROM models WHERE kind = 'embedding' AND is_default = true LIMIT 1")
        ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO models "
                "(id, name, provider_id, model_id, kind, is_default, params) "
                "VALUES (:id, 'mock-embed', :pid, 'mock-embed', 'embedding', :isdef, "
                "CAST('{}' AS jsonb))"
            ),
            {"id": str(uuid.uuid4()), "pid": provider_id, "isdef": bool(not has_default_embed)},
        )


def downgrade() -> None:
    # 가역 — mock-embed 행 제거(이름 소유 정책, f4a5와 동일 철학). default 플래그 승격은
    # "기본이 없을 때만" 걸었으므로, 되돌리면 chat 기본이 다시 비게 된다(원상). mock-llm
    # is_default를 false로 내린다. provider 이름/kind 원복은 비결정(파생 netloc 불명)이라 생략.
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM models WHERE name = 'mock-embed'"))
    conn.execute(
        sa.text("UPDATE models SET is_default = false WHERE name = 'mock-llm' AND kind = 'chat'")
    )
