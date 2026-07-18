"""스펙 162 검증 — mem0_memories 테이블이 없을 때 list_page가 502가 아니라 빈 상태.

비파괴: 별도 스키마(t162_verify)에서만 작업하고 public.mem0_memories는 절대 건드리지 않는다.
list_page는 self._dsn만 쓰므로 스텁으로 격리 호출한다(전체 Mem0Backend 인스턴스화=테이블 생성 회피).
"""

import os
import sys
import types
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "api", "src"))

import psycopg  # noqa: E402

from api.memory.mem0_backend import Mem0Backend, _sync_dsn  # noqa: E402

fails = 0


def check(cond: bool, label: str) -> None:
    global fails
    print(f"  {'ok ' if cond else 'FAIL'} {label}")
    if not cond:
        fails += 1


SCHEMA = "t162_verify"
base = _sync_dsn(
    os.environ.get("DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents")
)
# search_path를 빈 스키마로 고정한 DSN — mem0_memories가 이 스키마에서 해석되어 없으면 UndefinedTable.
sep = "&" if "?" in base else "?"
scoped_dsn = f"{base}{sep}options={quote(f'-c search_path={SCHEMA}')}"


def main() -> int:
    admin = psycopg.connect(base)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {SCHEMA}")

    stub = types.SimpleNamespace(_dsn=scoped_dsn)
    scope = {"user_id": "u-162"}

    # 1) 테이블 없음 → 빈 상태(before=UndefinedTable 예외로 502가 됐음).
    try:
        r = Mem0Backend.list_page(stub, scope, None, 20, 0)
        check(r == {"items": [], "total": 0}, f"H1 테이블 없음 → 빈 상태(0건), got {r}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"H1 예외 발생(수정 전 동작) → {type(exc).__name__}: {exc}")

    # 2) 회귀 — 같은 스키마에 mem0_memories 테이블+행 생성 시 정상 조회(catch가 정상 쿼리 안 삼킴).
    with admin.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {SCHEMA}.mem0_memories "
            "(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), payload jsonb)"
        )
        cur.execute(
            f"INSERT INTO {SCHEMA}.mem0_memories (payload) VALUES (%s::jsonb)",
            ['{"data": "회귀용 기억", "user_id": "u-162", "created_at": "2026-07-04T00:00:00Z"}'],
        )
    r2 = Mem0Backend.list_page(stub, scope, None, 20, 0)
    check(r2.get("total", 0) >= 1, f"H2 회귀: 테이블+행 → total≥1, got {r2.get('total')}")
    check(any("회귀용" in it["text"] for it in r2.get("items", [])), "H2 회귀: 행 본문 반환")

    # 3) 정리
    with admin.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    admin.close()

    print("PASS — 0 failed" if fails == 0 else f"FAIL — {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
