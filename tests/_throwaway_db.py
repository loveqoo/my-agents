"""일회용 DB 격리 러너(스펙 307) — 검증 스크립트를 **virgin DB**에서 돌린다.

동기: verify_*.py 다수가 공유 dev DB에 붙어, ambient 상태(예: 정리 대상 세션 133개)가 전역
집계·sample truncation에 새어들어 결정성을 깬다(스펙 056 등). 이 러너는 매 실행마다 임시 DB를
만들어 alembic 스키마 + `seed_if_empty`(트림된 정예: 에이전트 5·세션 0)만 심고, 대상 스크립트를
그 DB로 격리 실행한 뒤 **drop**한다. 라이브 `agents` DB는 절대 건드리지 않는다(smoke_303 계보).

사용:  uv run python tests/_throwaway_db.py tests/verify_056_session_cleanup_counter.py
       (대상 스크립트는 무수정 — DATABASE_URL만 임시 DB로 바뀌어 subprocess 실행된다.)

전제:  postgres 도달 가능(기본 dev 인스턴스), 롤 CREATE DATABASE 권한. dev 서버(8000)는 대상이
       요구하면 그때 필요(이 러너는 DB만 격리).
"""

import asyncio
import os
import subprocess
import sys
import uuid

import asyncpg
from sqlalchemy.engine import make_url

_DEFAULT = "postgresql+asyncpg://agent:agent@127.0.0.1:5432/agents"

# 견고 파싱(codex 스펙307): 순수 문자열 rpartition('/')은 쿼리스트링(`?sslrootcert=/tmp/x`)이 있으면
# 마지막 '/'가 db path가 아니라 query 내부라 db명 교체가 어긋나 **라이브 DB로 샐** 수 있다. SQLAlchemy
# URL 객체로 database 컴포넌트만 정확히 교체한다(포트·쿼리·자격증명 보존).


def _pg_dsn(url: str, dbname: str) -> str:
    """SQLAlchemy asyncpg URL → 순수 asyncpg dsn(드라이버 psycopg-less)으로, database만 교체."""
    return make_url(url).set(drivername="postgresql", database=dbname).render_as_string(
        hide_password=False
    )


def _sa_url(url: str, dbname: str) -> str:
    """SQLAlchemy asyncpg URL의 database만 교체(대상·부트스트랩에 넘길 DATABASE_URL)."""
    return make_url(url).set(database=dbname).render_as_string(hide_password=False)


async def _create(url: str, tmp: str) -> None:
    # 유지보수 DB(postgres)에 붙어 CREATE DATABASE. template1 collation 불일치 회피 위해 template0.
    conn = await asyncpg.connect(_pg_dsn(url, "postgres"))
    try:
        await conn.execute(f'CREATE DATABASE "{tmp}" TEMPLATE template0')
    finally:
        await conn.close()
    # pgvector 확장을 선설치(빠른 격리 부팅용 — 마이그레이션 b2c3d4e5f6a7도 자체 보장, 스펙 330 F4가 실증).
    conn = await asyncpg.connect(_pg_dsn(url, tmp))
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await conn.close()


async def _drop(url: str, tmp: str) -> None:
    conn = await asyncpg.connect(_pg_dsn(url, "postgres"))
    try:
        # 남은 커넥션 종료 후 DROP(자식 subprocess가 이미 종료됐어도 안전핀).
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            tmp,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{tmp}"')
    finally:
        await conn.close()


# 자식 부트스트랩 — 임시 DB에 실제 스키마(alembic head 단일 — 실패는 fail-fast, 스펙 330) + 첫 설치 시드를 심는다.
_BOOTSTRAP = (
    "import asyncio,sys;"
    "sys.path.insert(0, 'packages/api/src');"
    "from api.db import init_db, SessionLocal;"
    "from api.seed import seed_if_empty;"
    "\nasync def _m():\n"
    "    await init_db()\n"
    "    async with SessionLocal() as s:\n"
    "        await seed_if_empty(s)\n"
    "asyncio.run(_m())"
)


def main() -> None:
    if len(sys.argv) < 2:
        print("사용: python tests/_throwaway_db.py <target_verifier.py> [args...]")
        sys.exit(2)
    target = sys.argv[1]
    url = os.environ.get("DATABASE_URL", _DEFAULT)
    # 라이브 가드: 반드시 임시 DB에서만 동작(대상이 실수로 라이브를 치지 않게).
    tmp = f"agents_iso_{uuid.uuid4().hex[:12]}"
    if tmp.rsplit("/", 1)[-1] == "agents":  # 방어(불가능하지만 명시)
        print("거부: 임시 DB 이름이 라이브와 충돌")
        sys.exit(2)

    child_url = _sa_url(url, tmp)
    env = {**os.environ, "DATABASE_URL": child_url, "_THROWAWAY_DB": "1"}
    rc = 1
    # _create를 try 안에 둬 부분 생성(CREATE는 됐으나 extension 실패 등)도 finally가 drop한다(codex).
    try:
        asyncio.run(_create(url, tmp))
        print(f"== 일회용 DB [{tmp}] 부트스트랩(alembic+seed) ==")
        boot = subprocess.run(
            [sys.executable, "-c", _BOOTSTRAP], env=env, capture_output=True, text=True
        )
        if boot.returncode != 0:
            print("부트스트랩 실패:\n" + boot.stdout[-2000:] + boot.stderr[-2000:])
            sys.exit(1)
        print(f"== 대상 격리 실행: {target} ==")
        rc = subprocess.run([sys.executable, target, *sys.argv[2:]], env=env).returncode
    finally:
        asyncio.run(_drop(url, tmp))
        print(f"== 일회용 DB [{tmp}] drop 완료 ==")
    sys.exit(rc)


if __name__ == "__main__":
    main()
