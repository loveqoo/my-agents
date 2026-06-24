"""realign memory catalog to scope model (spec 020)

인지과학 분류(의미/일화/절차)의 4-항목 데모 카탈로그를 실제 동작과 1:1인 2-항목으로 재정렬한다:
인-컨텍스트 윈도우(mem0 아님)와 mem0 장기 메모리(스코프는 요청 userId로 자동 결정). 동시에
agents/agent_versions의 config.memories 배열에 박혀 있던 옛 이름을 새 이름으로 리맵한다.

Revision ID: c1d2e3f4a5b6
Revises: f9ae04bc5485
Create Date: 2026-06-24 00:00:00.000000

"""
import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "f9ae04bc5485"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 새 카탈로그(seed.py MEMORY_TYPES와 일치해야 함). (key, name, scope, body)
_NEW_TYPES = [
    ("단기(세션)", "단기(세션)", "In-context · mem0 아님",
     "현재 세션의 인-컨텍스트 윈도우(historyDepth) — 최근 N턴만 모델에 전달하는 컨텍스트 절단입니다. "
     "mem0 저장소가 아니며 세션이 끝나면 사라집니다."),
    ("장기 기억 (mem0)", "장기 기억 (mem0)", "Auto · userId 유무로 결정",
     "mem0 장기 메모리. 켜면 대화에서 사실을 추출·저장하고 매 턴 의미적으로 유사한 top-k를 회상합니다. "
     "스코프는 요청 userId로 자동 결정 — userId가 있으면 유저 단위(세션 가로지름)와 세션에 함께 저장하고, "
     "없으면 현재 세션에만 저장합니다."),
]

# 옛 이름 → 새 이름. 의미/일화/절차는 모두 mem0 장기 메모리로 흡수. 단기(세션)은 이름 동일(불변).
_RENAME = {
    "장기·의미론적": "장기 기억 (mem0)",
    "장기·일화적": "장기 기억 (mem0)",
    "절차적": "장기 기억 (mem0)",
}

# 옛 카탈로그(다운그레이드 복원용). (key, name, scope, body)
_OLD_TYPES = [
    ("단기(세션)", "단기(세션)", "Single session", "현재 세션의 인-컨텍스트 윈도우. 세션이 끝나면 비워집니다. 영속성 없음."),
    ("장기·의미론적", "장기·의미론적", "Cross-session", "벡터 스토어. 매 턴 전에 의미적으로 유사한 메모리 top-k를 검색합니다. TTL 없음."),
    ("장기·일화적", "장기·일화적", "Rolling window", "상호작용 이벤트 로그를 일 단위로 요약. 과거 대화·사건을 회상합니다."),
    ("절차적", "절차적", "Cross-session", "학습된 절차·선호·규칙을 누적. 반복 작업의 방법을 기억합니다."),
]


def _replace_catalog(conn, types) -> None:
    conn.execute(sa.text("DELETE FROM memory_types"))
    for key, name, scope, body in types:
        conn.execute(
            sa.text(
                "INSERT INTO memory_types (id, key, name, scope, body) "
                "VALUES (:id, :key, :name, :scope, :body)"
            ),
            {"id": str(uuid.uuid4()), "key": key, "name": name, "scope": scope, "body": body},
        )


def _remap_memories(conn, mapping: dict[str, str]) -> None:
    """agents/agent_versions의 config.memories 배열을 mapping으로 치환(중복 제거, 순서 보존)."""
    for table in ("agents", "agent_versions"):
        rows = conn.execute(sa.text(f"SELECT id, config FROM {table}")).fetchall()
        for rid, config in rows:
            cfg = config or {}
            mems = cfg.get("memories") or []
            new: list[str] = []
            for m in mems:
                mapped = mapping.get(m, m)
                if mapped not in new:
                    new.append(mapped)
            if new != mems:
                newcfg = {**cfg, "memories": new}
                conn.execute(
                    sa.text(f"UPDATE {table} SET config = CAST(:c AS jsonb) WHERE id = :id"),
                    {"c": json.dumps(newcfg, ensure_ascii=False), "id": rid},
                )


def upgrade() -> None:
    conn = op.get_bind()
    _replace_catalog(conn, _NEW_TYPES)
    _remap_memories(conn, _RENAME)


def downgrade() -> None:
    # 카탈로그는 옛 4-항목으로 복원. config.memories는 손실 변환(일화/절차 구분 불가)이라
    # "장기 기억 (mem0)" → "장기·의미론적"로만 되돌린다(대표값).
    conn = op.get_bind()
    _replace_catalog(conn, _OLD_TYPES)
    _remap_memories(conn, {"장기 기억 (mem0)": "장기·의미론적"})
