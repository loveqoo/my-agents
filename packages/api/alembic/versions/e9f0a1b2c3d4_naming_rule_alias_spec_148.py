"""5종(에이전트·컬렉션·페르소나·권한·MCP)에 alias + 이름 규칙 자동 변환 (spec 148)

식별 이름(name)=규칙 적용 참조 키, 별명(alias)=자유 표기. 규칙 위반 이름은 alias로 옮기고
name을 slugify로 변환하며, 이름을 참조하는 곳(에이전트/버전 config의 persona·vectorTables·
mcps·permissions·capabilities, casbin_rule의 per-cap 부여)을 old→new 매핑으로 함께 재작성한다
(move-breaks-references — 단방향 변환은 참조를 깬다). agents.name은 유니크 인덱스 신설.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-07-03 18:00:00.000000

"""
import json
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# api.naming의 스냅샷(마이그레이션은 자기완결 — 코드 진화와 분리)
_NAME_RE = re.compile(r"^[가-힣a-z0-9.\-]+$")
_TABLES = ("personas", "permissions", "collections", "mcp_servers", "agents")


def _slugify(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^가-힣a-z0-9.\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    return s or "이름-미상"


def _convert_table(bind, table: str) -> dict[str, str]:
    """위반/중복 이름 → 규칙 준수 유니크 이름으로 변환(alias에 원문 보존). old→new 매핑 반환.
    old 이름이 최종 이름 집합에 남아 있으면(중복의 첫 행 등) 매핑에서 제외 — 참조가 그 행으로
    계속 해석되므로 재작성하면 오히려 깨진다."""
    rows = bind.execute(sa.text(f"SELECT id, name FROM {table} ORDER BY name")).fetchall()  # noqa: S608 — 테이블명은 상수 튜플
    # 규칙 준수 행을 먼저 처리(codex 148 High): 준수 행이 이름을 보유한 뒤 비준수 행이 그 주변으로
    # dedupe돼야 한다. 반대 순서(collation에 따라 가능)면 "docs_kb"가 "docs-kb"를 선점해 기존
    # "docs-kb" 참조가 엉뚱한 행을 가리킨다.
    rows = sorted(rows, key=lambda r: (not bool(r[1] and _NAME_RE.match(r[1])), r[1] or ""))
    taken: set[str] = set()
    changed: list[tuple[str, str, str]] = []  # (id, old, new)
    for rid, name in rows:
        conforms = bool(name and _NAME_RE.match(name))
        base = name if conforms else _slugify(name or "")
        cand, i = base, 2
        while cand in taken:
            cand, i = f"{base}-{i}", i + 1
        taken.add(cand)
        if cand != name:
            changed.append((str(rid), name, cand))
    for rid, old, new in changed:
        bind.execute(
            sa.text(f"UPDATE {table} SET name = :new, alias = COALESCE(alias, :old) WHERE id = CAST(:id AS uuid)"),  # noqa: S608
            {"new": new, "old": old, "id": rid},
        )
    return {old: new for _, old, new in changed if old not in taken}


def _fix_config(cfg: dict, maps: dict[str, dict[str, str]]) -> bool:
    """에이전트 config 안의 이름 참조를 매핑으로 재작성. 변경 여부 반환."""
    changed = False
    p = cfg.get("persona")
    if isinstance(p, str) and p in maps["personas"]:
        cfg["persona"] = maps["personas"][p]
        changed = True
    for key, m in (
        ("vectorTables", maps["collections"]),
        ("mcps", maps["mcp_servers"]),
        ("permissions", maps["permissions"]),
    ):
        lst = cfg.get(key)
        if isinstance(lst, list):
            new = [m.get(x, x) if isinstance(x, str) else x for x in lst]
            if new != lst:
                cfg[key] = new
                changed = True
    caps = cfg.get("capabilities")
    if isinstance(caps, list):
        new_caps = []
        for c in caps:
            if isinstance(c, str) and c.startswith("rag:"):
                res = c[4:]
                c = "rag:" + maps["collections"].get(res, res)
            elif isinstance(c, str) and c.startswith("mcp:"):
                res = c[4:]
                server, sep, tool = res.partition("/")
                c = "mcp:" + maps["mcp_servers"].get(server, server) + sep + tool
            new_caps.append(c)
        if new_caps != caps:
            cfg["capabilities"] = new_caps
            changed = True
    return changed


def _rewrite_cap_obj(obj: str, maps: dict[str, dict[str, str]]) -> str:
    """casbin per-cap object `capability:{kind}:{resource}` 재작성(mcp는 server[/tool])."""
    if obj.startswith("capability:rag:"):
        res = obj[len("capability:rag:"):]
        return "capability:rag:" + maps["collections"].get(res, res)
    if obj.startswith("capability:mcp:"):
        res = obj[len("capability:mcp:"):]
        server, sep, tool = res.partition("/")
        return "capability:mcp:" + maps["mcp_servers"].get(server, server) + sep + tool
    return obj


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("alias", sa.String(200), nullable=True))

    bind = op.get_bind()
    maps = {t: _convert_table(bind, t) for t in _TABLES}

    # 이름 참조 재작성 — agents.config + agent_versions.config
    for table in ("agents", "agent_versions"):
        rows = bind.execute(sa.text(f"SELECT id, config FROM {table}")).fetchall()  # noqa: S608
        for rid, cfg in rows:
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            if not isinstance(cfg, dict):
                continue
            if _fix_config(cfg, maps):
                bind.execute(
                    sa.text(f"UPDATE {table} SET config = CAST(:cfg AS jsonb) WHERE id = CAST(:id AS uuid)"),  # noqa: S608
                    {"cfg": json.dumps(cfg, ensure_ascii=False), "id": str(rid)},
                )

    # casbin per-cap 부여 재작성(capability:rag/mcp:{이름}) — casbin_rule이 아직 없으면 스킵
    has_casbin = bind.execute(sa.text("SELECT to_regclass('casbin_rule')")).scalar()
    if has_casbin:
        rows = bind.execute(
            sa.text("SELECT id, v1 FROM casbin_rule WHERE v1 LIKE 'capability:rag:%' OR v1 LIKE 'capability:mcp:%'")
        ).fetchall()
        for rid, v1 in rows:
            new_v1 = _rewrite_cap_obj(v1, maps)
            if new_v1 != v1:
                bind.execute(
                    sa.text("UPDATE casbin_rule SET v1 = :v WHERE id = :id"),
                    {"v": new_v1, "id": rid},
                )

    op.create_index("uq_agents_name", "agents", ["name"], unique=True)


def downgrade() -> None:
    # 이름 변환·참조 재작성은 되돌리지 않는다(변환 후 이름도 유효 — alias에 원문 보존됨).
    op.drop_index("uq_agents_name", table_name="agents")
    for t in reversed(_TABLES):
        op.drop_column(t, "alias")
