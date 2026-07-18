"""verify_330 — init_db 마이그레이션 fail-fast(create_all 폴백 제거, 스펙 330).

스크래치 DB 2개를 자체 생성(_throwaway_db 헬퍼 재사용)·부팅은 서브프로세스로(엔진이 import 시
DATABASE_URL에 바인딩되므로 프로세스 격리가 정확):
  F1 fail-fast: alembic_version='deadbeef'(코드가 모르는 리비전) DB → init_db **비정상 종료** +
     조치 메시지, **create_all 부수효과 0**(테이블은 alembic_version 하나뿐)·버전 미변경(스탬프
     안 함)·"폴백" 문구 부재 — 구 조용한 우회의 여집합 전부 단언.
  F2 virgin 정상: 빈 DB → init_db 성공 → alembic_version==파일 그래프의 단일 head·rag_chunks
     존재(확장+전 체인)·token_count 부재(329 경유).
  F3 멱등: 같은 DB 2회째 init_db 무예외.
  F4 확장 보장(codex 330 P2): pgvector **선설치 없이** 만든 DB도 부팅 성공 — 구 폴백이 지탱하던
     "CREATE EXTENSION 보장"이 마이그레이션 b2c3d4e5f6a7로 실제 승계됐음을 실증(F2의 _create는
     확장을 선설치해 이 보장을 검증 못 한다).
실행: uv run python tests/verify_330_failfast.py   (postgres 도달 + CREATE DATABASE 권한 필요)
"""

import asyncio
import glob
import os
import re
import subprocess
import sys
import uuid

import asyncpg

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "tests"))
from _throwaway_db import _DEFAULT, _create, _drop, _pg_dsn, _sa_url  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


_BOOT = (
    "import asyncio,sys;"
    "sys.path.insert(0, 'packages/api/src');"
    "from api.db import init_db;"
    "asyncio.run(init_db())"
)


def _boot(url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-c", _BOOT], env=env, capture_output=True, text=True, cwd=_ROOT
    )


def _file_head() -> str:
    """마이그레이션 파일 헤더에서 단일 head 계산(verify_329 V3 미러)."""
    revs, downs = {}, {}
    for f in glob.glob(os.path.join(_ROOT, "packages", "api", "alembic", "versions", "*.py")):
        src = open(f).read()
        r = re.search(r'^revision(?::[^=]*)?\s*=\s*["\'](\w+)["\']', src, re.M)
        d = re.search(r'^down_revision(?::[^=]*)?\s*=\s*(?:["\'](\w+)["\']|None)', src, re.M)
        revs[r.group(1)] = f
        downs[r.group(1)] = d.group(1) if d and d.group(1) else None
    heads = [r for r in revs if r not in (set(downs.values()) - {None})]
    assert len(heads) == 1, f"단일 head 아님: {heads}"
    return heads[0]


async def _q(url: str, dbname: str, sql: str) -> list:
    conn = await asyncpg.connect(_pg_dsn(url, dbname))
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


async def _create_no_ext(url: str, dbname: str) -> None:
    """CREATE DATABASE만(확장 선설치 없음) — F4가 마이그레이션의 확장 보장을 실증하기 위한 경로."""
    conn = await asyncpg.connect(_pg_dsn(url, "postgres"))
    try:
        await conn.execute(f'CREATE DATABASE "{dbname}" TEMPLATE template0')
    finally:
        await conn.close()


async def main() -> None:
    base = os.environ.get("DATABASE_URL", _DEFAULT)
    db_broken = f"agents_v330_broken_{uuid.uuid4().hex[:8]}"
    db_virgin = f"agents_v330_virgin_{uuid.uuid4().hex[:8]}"
    db_noext = f"agents_v330_noext_{uuid.uuid4().hex[:8]}"
    try:
        await _create(base, db_broken)
        await _create(base, db_virgin)
        await _create_no_ext(base, db_noext)

        # ── F1: 코드가 모르는 리비전 → fail-fast + 부수효과 0 ──
        conn = await asyncpg.connect(_pg_dsn(base, db_broken))
        try:
            await conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
            await conn.execute("INSERT INTO alembic_version VALUES ('deadbeef')")
        finally:
            await conn.close()
        r1 = _boot(_sa_url(base, db_broken))
        out1 = r1.stdout + r1.stderr
        check(r1.returncode != 0, f"F1a init_db 비정상 종료 (rc={r1.returncode})")
        check("마이그레이션 실패" in out1 and "alembic current" in out1, "F1b 조치 메시지 출력")
        check("폴백" not in out1.replace("폴백 없음", ""), "F1c '폴백합니다' 류 문구 부재")
        tables = await _q(
            base,
            db_broken,
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
        )
        names = sorted(t[0] for t in tables)
        check(names == ["alembic_version"], f"F1d create_all 부수효과 0 (tables={names})")
        ver = await _q(base, db_broken, "SELECT version_num FROM alembic_version")
        check(ver[0][0] == "deadbeef", f"F1e 버전 미변경(스탬프 안 함) (got {ver[0][0]})")

        # ── F2: virgin DB → alembic 전 체인으로 정상 부팅 ──
        r2 = _boot(_sa_url(base, db_virgin))
        out2 = r2.stdout + r2.stderr
        check(r2.returncode == 0, f"F2a virgin 부팅 성공 (rc={r2.returncode}, tail={out2[-300:]})")
        check("폴백" not in out2, "F2b 폴백 문구 부재(순수 alembic 경로)")
        head = _file_head()
        ver2 = await _q(base, db_virgin, "SELECT version_num FROM alembic_version")
        check(ver2[0][0] == head, f"F2c alembic_version==파일 head({head}) (got {ver2[0][0]})")
        cols = await _q(
            base,
            db_virgin,
            "SELECT column_name FROM information_schema.columns WHERE table_name='rag_chunks'",
        )
        colnames = sorted(c[0] for c in cols)
        check(
            "embedding" in colnames and "token_count" not in colnames,
            f"F2d rag_chunks 존재+329 반영 (cols={colnames})",
        )

        # ── F3: 멱등 재부팅 ──
        r3 = _boot(_sa_url(base, db_virgin))
        check(r3.returncode == 0, f"F3 재부팅(2회째 init_db) 무예외 (rc={r3.returncode})")

        # ── F4: 확장 선설치 없는 DB → 마이그레이션이 확장까지 보장 ──
        r4 = _boot(_sa_url(base, db_noext))
        out4 = r4.stdout + r4.stderr
        check(
            r4.returncode == 0,
            f"F4a 확장 미설치 DB 부팅 성공 (rc={r4.returncode}, tail={out4[-300:]})",
        )
        ext = await _q(base, db_noext, "SELECT extname FROM pg_extension WHERE extname='vector'")
        check(bool(ext), "F4b vector 확장이 마이그레이션으로 생성됨(b2c3d4e5f6a7 승계)")
    finally:
        await _drop(base, db_broken)
        await _drop(base, db_virgin)
        await _drop(base, db_noext)

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY330_OK — {passed}건 전부 통과")


asyncio.run(main())
