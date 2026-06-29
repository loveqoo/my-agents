"""allowed_hosts table + env bootstrap import (spec 064)

SSRF allowlist(스펙 042)를 env(`A2A_ALLOWED_HOSTS`)에서 **DB `allowed_hosts` 테이블**로 옮긴다 —
무재시작 관리(Admin UI/API)·`A2A_` 접두어 제거(공용 allowlist). 이 마이그레이션이:
1. `allowed_hosts` 테이블 생성(정상 alembic 경로 = path A).
2. env 값을 **정확히 1회** DB로 부트스트랩 임포트(revision-stamped → 재실행 안 됨).

049 재시드 footgun 차단: env→DB 임포트를 *마이그레이션 1회*로만 한다. 관리자가 UI로 목록을 비운 뒤
재부팅해도, 이 마이그레이션은 이미 스탬프돼 다시 돌지 않으므로 env가 host를 *되살리지 않는다*(DB가
진실원). create_all 폴백(path B)은 이 임포트를 타지 않고 **빈 allowlist로 시작**(fail-closed — 더
제한적이라 안전, 062 양 경로는 안전 상태로 수렴). env→DB 정규화는 `api.net_guard.normalize_allowed_host`
를 재사용해 런타임 매칭과 동형(드리프트 방지).

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-29 00:00:00.000000

"""
import os
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "allowed_hosts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host"),
    )

    # env→DB 부트스트랩 1회 임포트(`ALLOWED_HOSTS` 우선, 구 `A2A_ALLOWED_HOSTS` 폴백).
    raw = os.environ.get("ALLOWED_HOSTS")
    if raw is None:
        legacy = os.environ.get("A2A_ALLOWED_HOSTS")
        if legacy is not None:
            print(  # noqa: T201 — 마이그레이션 1회 로그(구 변수명 폴백 deprecation 안내)
                "[spec 064] A2A_ALLOWED_HOSTS는 deprecated입니다 — ALLOWED_HOSTS로 바꾸세요"
                "(부트스트랩 임포트에만 쓰이며, 런타임은 DB allowed_hosts를 봅니다)."
            )
        raw = legacy or ""

    # 런타임 매칭과 동형 정규화(드리프트 방지). 잘못된 항목은 건너뛰고 로그만.
    try:
        from api.net_guard import normalize_allowed_host
    except Exception:  # noqa: BLE001 — 임포트 불가 시 부트스트랩 임포트만 생략(테이블은 이미 생성)
        normalize_allowed_host = None  # type: ignore[assignment]

    hosts: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if normalize_allowed_host is None:
            # normalize 임포트 불가(sys.path 등) → 미정규화 저장 대신 건너뜀(fail-closed, 적대리뷰 P2).
            # 미정규화로 저장하면 `*` 같은 항목이 CRUD 검증을 우회해 들어와 드리프트가 난다.
            # 부트스트랩이 비어도 빈 목록이 더 안전한 방향이고 UI로 추가하면 된다.
            print(f"[spec 064] normalize 불가 → 부트스트랩 항목 건너뜀(fail-closed): {part!r}")  # noqa: T201
            continue
        try:
            hosts.append(normalize_allowed_host(part))
        except ValueError as exc:
            print(f"[spec 064] allowlist 항목 건너뜀({part!r}): {exc}")  # noqa: T201

    seen: set[str] = set()
    conn = op.get_bind()
    for h in hosts:
        if h in seen:
            continue
        seen.add(h)
        conn.execute(
            sa.text(
                "INSERT INTO allowed_hosts (id, host, note) VALUES (:id, :host, :note)"
            ),
            {"id": uuid.uuid4(), "host": h, "note": "env 부트스트랩(스펙 064)"},
        )


def downgrade() -> None:
    op.drop_table("allowed_hosts")
