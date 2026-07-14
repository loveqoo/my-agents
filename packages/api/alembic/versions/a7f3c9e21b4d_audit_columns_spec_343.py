"""감사 컬럼(created_at/updated_at/created_by/updated_by) — 우리 소유 27테이블 (스펙 343).

- 기존 created_at 18개는 **재사용**(중복 생성 금지), 없는 곳만 추가.
- 백필: created_at=기존 유사 컬럼(started_at/requested_at) 또는 now(), updated_at=created_at,
  created_by/updated_by='unknown'(과거 행은 주체를 알 수 없다 — 정직).
- 이후 NOT NULL 승격 → 신규 행은 반드시 채워짐(코드 누락 시 조용히 통과하지 않고 즉시 실패).
- **DB 트리거·함수는 만들지 않는다**(사용자 기각 — 로직이 DB에 숨는 방식 금지). 값은 앱 계층
  (api/audit.py의 AuditMixin: 컬럼 default/onupdate)이 채운다.
- 외부 라이브러리 소유 테이블(user·accesstoken·casbin_rule·checkpoint*·mem0_memories)은 제외.

Revision ID: a7f3c9e21b4d
Revises: d5795d21f6a2
"""

import sqlalchemy as sa

from alembic import op

revision: str = "a7f3c9e21b4d"
down_revision: str | None = "d5795d21f6a2"
branch_labels: str | None = None
depends_on: str | None = None

# (테이블, 이미 있는 created_at 대체 컬럼 or None) — 백필의 시간 출처.
TABLES: list[tuple[str, str | None]] = [
    ("personas", "created_at"),
    ("memory_types", None),
    ("collections", "created_at"),
    ("documents", "created_at"),
    ("rag_chunks", "created_at"),
    ("document_blobs", "created_at"),
    ("collection_reindex_events", "created_at"),
    ("providers", "created_at"),
    ("models", "created_at"),
    ("mcp_servers", None),
    ("app_settings", None),
    ("node_templates", "created_at"),
    ("agents", "created_at"),
    ("agent_versions", "created_at"),
    ("sessions", "started_at"),  # 도메인 컬럼(세션 시작) — 감사 created_at의 백필 출처로만 사용
    ("messages", "created_at"),
    ("message_feedback", "created_at"),
    ("approvals", "requested_at"),  # 도메인 컬럼(승인 요청 시각)
    ("roles", None),
    ("batch_runs", "started_at"),
    ("batch_config", None),
    ("memory_snapshots", "created_at"),
    ("allowed_hosts", "created_at"),
    ("eval_datasets", "created_at"),
    ("eval_cases", "created_at"),
    ("eval_runs", "started_at"),
    ("eval_case_results", "created_at"),
]

# 이미 created_at 컬럼이 **그 이름 그대로** 있는 테이블(추가하지 않는다).
HAS_CREATED_AT = {t for t, src in TABLES if src == "created_at"}
# 이미 updated_at이 있는 테이블(추가하지 않는다).
HAS_UPDATED_AT = {"personas", "mcp_servers", "message_feedback", "eval_datasets", "batch_config"}

UNKNOWN = "unknown"


def upgrade() -> None:
    # ⓪ 이름 충돌 해소 — message_feedback에 이미 있던 `created_by`(= 피드백 작성자 auth User UUID,
    #    스펙 209)는 **감사용 created_by(이메일 로컬파트)와 다른 개념**이다. 다른 테이블이 같은 개념을
    #    부르는 이름(owner_id)으로 개명한다. 컬럼 rename이므로 유니크 인덱스는 자동으로 따라온다.
    op.alter_column("message_feedback", "created_by", new_column_name="owner_id")

    for table, time_src in TABLES:
        # ① 컬럼 추가(nullable) — 없는 것만.
        if table not in HAS_CREATED_AT:
            op.add_column(
                table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
            )
        if table not in HAS_UPDATED_AT:
            op.add_column(
                table, sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
            )
        op.add_column(table, sa.Column("created_by", sa.String(length=80), nullable=True))
        op.add_column(table, sa.Column("updated_by", sa.String(length=80), nullable=True))

        # ② 백필 — 시간은 기존 유사 컬럼에서(없으면 now()), 주체는 알 수 없으므로 'unknown'.
        src = time_src or "now()"
        op.execute(f"UPDATE {table} SET created_at = COALESCE(created_at, {src}, now())")
        op.execute(f"UPDATE {table} SET updated_at = COALESCE(updated_at, created_at)")
        op.execute(f"UPDATE {table} SET created_by = COALESCE(created_by, '{UNKNOWN}')")
        op.execute(f"UPDATE {table} SET updated_by = COALESCE(updated_by, '{UNKNOWN}')")

        # ③ NOT NULL 승격 — 이후 신규 행은 DB가 4개 존재를 보장(감사 누락이 조용히 통과 못 함).
        op.alter_column(table, "created_at", nullable=False, server_default=sa.text("now()"))
        op.alter_column(table, "updated_at", nullable=False, server_default=sa.text("now()"))
        op.alter_column(table, "created_by", nullable=False)
        op.alter_column(table, "updated_by", nullable=False)


def downgrade() -> None:
    # 순서 주의(codex 343 P1): 감사 컬럼을 **먼저** 지운 뒤에 개명을 되돌린다. 반대로 하면
    # message_feedback에 감사 created_by가 아직 남아 있어 owner_id→created_by rename이 충돌한다.
    for table, _src in TABLES:
        op.drop_column(table, "updated_by")
        op.drop_column(table, "created_by")
        if table not in HAS_UPDATED_AT:
            op.drop_column(table, "updated_at")
        if table not in HAS_CREATED_AT:
            op.drop_column(table, "created_at")
        # 기존 created_at/updated_at(343 이전부터 있던 컬럼)은 원래도 NOT NULL + server_default now()
        # 였으므로 손대지 않는다(pre-343 속성 그대로 — codex P3).
    op.alter_column("message_feedback", "owner_id", new_column_name="created_by")
