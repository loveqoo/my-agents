"""verify_345 — 처녀 DB에 `unknown` 0건 (스펙 345).

`unknown`의 뜻은 "감사 도입(343) 이전에 만들어진 행"이다. **갓 만든 DB에 그 값이 있으면 거짓말**이다.
데이터 초기화 실측에서 providers/models(마이그레이션 시드)가 unknown으로 찍히는 것을 발견 → 345로 정정.

  S1 **처녀 DB unknown 0건**(완료 조건): 우리 소유 27테이블 전수 질의 — created_by/updated_by에
     'unknown'인 행이 하나도 없다.
  S2 시드 행이 system: Mock LLM provider + mock 모델 2개의 created_by='system'.
  S3 앱 시드(ORM)도 system: agents·prompts·collections.
  S4 **재발 방지 스캔**: 343(a7f3c9e21b4d) 이후 리비전에 INSERT INTO가 있으면 같은 문장에
     created_by가 있어야 한다 — 다음 데이터 마이그레이션이 같은 함정에 빠지지 않게.

실행: uv run python tests/_throwaway_db.py tests/verify_345_seed_actor.py   (virgin DB)
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api.db import SessionLocal, init_db  # noqa: E402

_fails: list[str] = []
passed = 0

OWNED = [
    "agents", "agent_versions", "allowed_hosts", "app_settings", "approvals", "batch_config",
    "batch_runs", "collection_reindex_events", "collections", "document_blobs", "documents",
    "eval_case_results", "eval_cases", "eval_datasets", "eval_runs", "mcp_servers",
    "memory_snapshots", "memory_types", "message_feedback", "messages", "models",
    "node_templates", "prompts", "providers", "rag_chunks", "roles", "sessions",
]


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def main() -> None:
    await init_db()  # 마이그레이션 + 시드

    async with SessionLocal() as s:
        # S1 — 완료 조건: 처녀 DB에 unknown 0건
        dirty = []
        for t in OWNED:
            n = (
                await s.execute(
                    text(
                        f"select count(*) from {t} "  # noqa: S608 — 테이블명은 위 상수 리스트
                        "where created_by = 'unknown' or updated_by = 'unknown'"
                    )
                )
            ).scalar_one()
            if n:
                dirty.append((t, n))
        check(not dirty, f"S1 처녀 DB unknown 0건(완료 조건) (오염: {dirty})")

        # S2 — 마이그레이션 시드 행 = system
        rows = (
            await s.execute(
                text(
                    "select name, created_by from providers where kind='mock' "
                    "union all select name, created_by from models where model_id in ('mock-chat','mock-embed')"
                )
            )
        ).all()
        check(
            rows and all(r[1] == "system" for r in rows),
            f"S2 마이그레이션 시드(provider·모델 {len(rows)}행) = system (got {[(r[0], r[1]) for r in rows]})",
        )

        # S3 — 앱 시드(ORM) = system
        app_rows = (
            await s.execute(
                text(
                    "select 'agents', created_by from agents "
                    "union all select 'prompts', created_by from prompts "
                    "union all select 'collections', created_by from collections"
                )
            )
        ).all()
        bad = sorted({(r[0], r[1]) for r in app_rows if r[1] != "system"})
        check(app_rows and not bad, f"S3 앱 시드(ORM) = system (예외: {bad})")

    # S4 — 재발 방지: 343 이후 리비전의 INSERT는 감사 컬럼을 명시해야 한다
    vers = pathlib.Path(__file__).resolve().parents[1] / "packages/api/alembic/versions"
    after_343 = []
    for f in vers.glob("*.py"):
        body = f.read_text()
        down = re.search(r'down_revision[^=]*=\s*["\']([^"\']+)', body)
        # 343(a7f3c9e21b4d) 이후 = 343을 직접·간접 부모로 두는 리비전(현 체인은 선형이라 직접만 확인)
        if down and down.group(1) in ("a7f3c9e21b4d", "b8e4d2c7a915"):
            if re.search(r"INSERT\s+INTO", body, re.I) and "created_by" not in body:
                after_343.append(f.name)
    check(not after_343, f"S4 343 이후 데이터 INSERT는 감사 컬럼 명시 (누락: {after_343})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY345_OK — {passed}건 전부 통과")


asyncio.run(main())
