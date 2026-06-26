"""provider entity — extract provider from models (spec 035)

ModelConfig의 인라인 연결처(provider/base_url/api_key)를 1급 `providers` 테이블로 분리하고
models는 `provider_id` FK(ondelete RESTRICT)로 참조한다.

데이터 마이그레이션(승인된 결정):
  - 그룹핑 키 = base_url (Fernet 비결정 암호화라 api_key 암호문 비교 불가 → 같은 엔드포인트=같은 provider).
  - api_key = 그룹 내 첫 비공백 값 채택(같은 base_url의 모델들은 같은 자격증명 공유 전제).
  - provider name = base_url의 netloc에서 파생(충돌 시 suffix).
  - protocol = 그룹 내 기존 provider 문자열.

가역: downgrade는 provider 컬럼을 models로 되돌리고 providers 테이블을 제거한다.

Revision ID: a1b2c3d4e5f6
Revises: 0301dea55e1a
Create Date: 2026-06-27 00:00:00.000000

"""
import logging
import uuid
from typing import Sequence, Union
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

log = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "0301dea55e1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _provider_name(base_url: str, used: set[str]) -> str:
    """base_url의 netloc에서 읽기 쉬운 고유 이름 파생(충돌 시 suffix)."""
    netloc = urlsplit(base_url).netloc or base_url or "provider"
    name = netloc
    i = 2
    while name in used:
        name = f"{netloc} ({i})"
        i += 1
    used.add(name)
    return name


def upgrade() -> None:
    conn = op.get_bind()

    # 1) providers 테이블 생성.
    op.create_table(
        "providers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("protocol", sa.String(length=40), nullable=False),
        sa.Column("base_url", sa.String(length=400), nullable=False),
        sa.Column("api_key", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # 2) 기존 models를 base_url별로 묶어 provider 생성 + base_url→provider_id 매핑.
    rows = conn.execute(sa.text("SELECT base_url, provider, api_key FROM models")).fetchall()
    groups: dict[str, dict] = {}
    for base_url, provider, api_key in rows:
        g = groups.setdefault(
            base_url or "",
            {"protocol": provider or "openai-compatible", "api_key": None, "keys": []},
        )
        if g["api_key"] is None and api_key:
            g["api_key"] = api_key  # 그룹 내 첫 비공백 자격증명
        if api_key:
            g["keys"].append(api_key)

    # 손실 가시화(no silent drops): 같은 base_url에 서로 다른 자격증명이 섞여 있으면 첫 키만
    # 채택되고 나머지는 버려진다. Fernet는 비결정 암호화라 암호문 비교론 구분 못 하므로
    # 복호화해 평문이 실제로 충돌하는 경우에만 경고한다(같은 키의 다른 암호문은 무시).
    for base_url, g in groups.items():
        if len(g["keys"]) > 1:
            try:
                from api import crypto

                plains = {crypto.decrypt(k) for k in g["keys"]}
            except Exception:  # 복호화 불가(키 부재 등) — 가시화는 베스트에포트, 마이그레이션은 진행.
                plains = set(g["keys"])
            if len(plains) > 1:
                log.warning(
                    "스펙035 마이그레이션: base_url=%r 에 서로 다른 api_key %d종이 있어 첫 키만 "
                    "보존하고 나머지는 버립니다(승인된 base_url 그룹핑). 필요하면 마이그레이션 후 "
                    "provider를 분리하세요.",
                    base_url,
                    len(plains),
                )

    used: set[str] = set()
    base_to_pid: dict[str, str] = {}
    for base_url, g in groups.items():
        pid = str(uuid.uuid4())
        base_to_pid[base_url] = pid
        conn.execute(
            sa.text(
                "INSERT INTO providers (id, name, protocol, base_url, api_key) "
                "VALUES (:id, :name, :protocol, :base_url, :api_key)"
            ),
            {
                "id": pid,
                "name": _provider_name(base_url, used),
                "protocol": g["protocol"],
                "base_url": base_url,
                "api_key": g["api_key"],
            },
        )

    # 3) models.provider_id 추가(우선 nullable) → 매핑으로 채움.
    op.add_column("models", sa.Column("provider_id", sa.UUID(), nullable=True))
    for base_url, pid in base_to_pid.items():
        conn.execute(
            sa.text("UPDATE models SET provider_id = :pid WHERE COALESCE(base_url, '') = :base"),
            {"pid": pid, "base": base_url},
        )

    # 4) NOT NULL + FK(ondelete RESTRICT) 확정.
    op.alter_column("models", "provider_id", nullable=False)
    op.create_foreign_key(
        "fk_models_provider_id", "models", "providers", ["provider_id"], ["id"], ondelete="RESTRICT"
    )

    # 5) 인라인 연결처 컬럼 제거.
    op.drop_column("models", "provider")
    op.drop_column("models", "base_url")
    op.drop_column("models", "api_key")


def downgrade() -> None:
    conn = op.get_bind()

    # 1) 인라인 컬럼 복구(우선 nullable/디폴트).
    op.add_column("models", sa.Column("provider", sa.String(length=40), nullable=True))
    op.add_column("models", sa.Column("base_url", sa.String(length=400), nullable=True))
    op.add_column("models", sa.Column("api_key", sa.String(length=400), nullable=True))

    # 2) provider에서 값 복원.
    conn.execute(
        sa.text(
            "UPDATE models m SET provider = p.protocol, base_url = p.base_url, api_key = p.api_key "
            "FROM providers p WHERE m.provider_id = p.id"
        )
    )
    conn.execute(sa.text("UPDATE models SET provider = 'openai-compatible' WHERE provider IS NULL"))
    conn.execute(sa.text("UPDATE models SET base_url = '' WHERE base_url IS NULL"))

    # 3) NOT NULL 디폴트 확정 + provider_id/테이블 제거.
    op.alter_column("models", "provider", nullable=False, server_default="openai-compatible")
    op.alter_column("models", "base_url", nullable=False, server_default="")
    op.drop_constraint("fk_models_provider_id", "models", type_="foreignkey")
    op.drop_column("models", "provider_id")
    op.drop_table("providers")
