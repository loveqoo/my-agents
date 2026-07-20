"""virgin DB 격리 공용 헬퍼(스펙 414) — `_throwaway_db.py`(테스트당)와 `run_suite.py`(run당 db 그룹)가
공유한다(사본 0 — 회고 261). 임시 DB 생성+부트스트랩(alembic head + seed_if_empty)+drop 로직을 한 곳에.

라이브 `agents` DB는 절대 건드리지 않는다(database 컴포넌트만 SQLAlchemy URL로 정확히 교체 —
순수 rpartition은 쿼리스트링에 '/'가 있으면 라이브로 샐 수 있다, 스펙 307 codex).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import asyncpg
from sqlalchemy.engine import make_url

DEFAULT_URL = "postgresql+asyncpg://agent:agent@127.0.0.1:5432/agents"

# 자식 부트스트랩 — 임시 DB에 앱 부팅과 **동일 순서**로: alembic head(스키마) + init_authz(casbin_rule
# +기본 정책 — 앱 startup이 만드는 테이블이라 alembic엔 없다, 스펙 414) + seed_if_empty(첫 설치 시드).
# init_authz 누락 시 policy·인가 쓰는 테스트가 "casbin_rule does not exist"로 실패(하네스가 드러냄).
_BOOTSTRAP = (
    "import asyncio,sys;"
    "sys.path.insert(0, 'packages/api/src');"
    "from api.db import init_db, SessionLocal;"
    "from api.seed import seed_if_empty;"
    "from api.authz import init_authz;"
    "\nasync def _m():\n"
    "    await init_db()\n"
    "    await init_authz()\n"
    "    async with SessionLocal() as s:\n"
    "        await seed_if_empty(s)\n"
    "asyncio.run(_m())"
)


def pg_dsn(url: str, dbname: str) -> str:
    """SQLAlchemy asyncpg URL → 순수 asyncpg dsn, database만 교체(유지보수 접속용)."""
    return make_url(url).set(drivername="postgresql", database=dbname).render_as_string(hide_password=False)


def sa_url(url: str, dbname: str) -> str:
    """SQLAlchemy asyncpg URL의 database만 교체(대상·부트스트랩에 넘길 DATABASE_URL)."""
    return make_url(url).set(database=dbname).render_as_string(hide_password=False)


async def _create(url: str, tmp: str) -> None:
    conn = await asyncpg.connect(pg_dsn(url, "postgres"))
    try:
        # template1 collation 불일치 회피 위해 template0.
        await conn.execute(f'CREATE DATABASE "{tmp}" TEMPLATE template0')
    finally:
        await conn.close()
    conn = await asyncpg.connect(pg_dsn(url, tmp))
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await conn.close()


async def _drop(url: str, tmp: str) -> None:
    conn = await asyncpg.connect(pg_dsn(url, "postgres"))
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            tmp,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{tmp}"')
    finally:
        await conn.close()


@contextlib.contextmanager
def fresh_db(label: str = "iso") -> Iterator[tuple[str, dict]]:
    """virgin DB를 만들어 (child DATABASE_URL, subprocess env)를 yield하고, 종료 시 drop한다.

    - label='iso': 테스트당(throwaway) / 'run': run당(그물 db 그룹).
    - 부트스트랩 실패는 RuntimeError로 던진다(finally가 drop 보장 — 부분 생성도 정리).
    - 라이브 무접촉: 임시 DB 이름은 `agents_{label}_{rand}`, 라이브 'agents'와 충돌 불가.
    """
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    tmp = f"agents_{label}_{uuid.uuid4().hex[:12]}"
    child_url = sa_url(url, tmp)
    env = {**os.environ, "DATABASE_URL": child_url, "_THROWAWAY_DB": "1"}
    try:
        asyncio.run(_create(url, tmp))
        boot = subprocess.run(
            [sys.executable, "-c", _BOOTSTRAP], env=env, capture_output=True, text=True
        )
        if boot.returncode != 0:
            raise RuntimeError(
                f"virgin DB [{tmp}] 부트스트랩 실패:\n{boot.stdout[-2000:]}{boot.stderr[-2000:]}"
            )
        yield child_url, env
    finally:
        asyncio.run(_drop(url, tmp))
