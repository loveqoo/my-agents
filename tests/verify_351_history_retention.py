"""verify_351 — 실행 이력 회수 (스펙 351).

eval_runs · batch_runs · memory_snapshots — 셋 다 "무슨 일이 있었나"의 기록인데 **삭제 경로가 없었다**.
348로 배치가 실제로 돌기 시작해 batch_runs가 매시 쌓이므로 **청소부의 발자국도 치운다.**

  H1 오래된 eval_runs 삭제 + **eval_case_results가 CASCADE로 함께** 사라진다(고아 0).
  H2 **문제집별 최근 10런은 나이와 무관하게 보존** — 회수가 성적 추이 그래프를 죽이면 안 된다.
  H3 오래된 batch_runs·memory_snapshots 삭제, 최근 것은 보존.
  H4 dry-run은 세기만 하고 삭제 0.
  H5 보존기간 <1이면 잡 비활성(delete-all 금지).

실행: uv run python tests/verify_351_history_retention.py
"""

import asyncio
import pathlib
import sys
import uuid
from datetime import UTC, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api.batch.jobs import cleanup_history  # noqa: E402
from api.db import SessionLocal  # noqa: E402

MARK = f"v351-{uuid.uuid4().hex[:6]}"
_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def _setup() -> str:
    """문제집 1개 + 오래된 런 13개(케이스 결과 1개씩) + 최근 런 1개 + 오래된 배치런·스냅샷."""
    old = datetime.now(UTC) - timedelta(days=200)
    recent = datetime.now(UTC) - timedelta(days=1)
    async with SessionLocal() as s:
        ds_id = (
            await s.execute(
                text(
                    "insert into eval_datasets (id, name, kind, created_at, updated_at, created_by, updated_by) "
                    "values (gen_random_uuid(), :n, 'agent', now(), now(), 'system', 'system') returning id"
                ),
                {"n": f"{MARK}-dataset"},
            )
        ).scalar_one()
        for i in range(13):  # 오래된 런 13개 → 최근 10개는 보존, 3개만 삭제 대상
            run_id = (
                await s.execute(
                    text(
                        "insert into eval_runs (id, dataset_id, status, started_at, created_at, "
                        "updated_at, created_by, updated_by) values (gen_random_uuid(), :d, 'ok', :t, "
                        "now(), now(), 'system', 'system') returning id"
                    ),
                    {"d": ds_id, "t": old + timedelta(seconds=i)},
                )
            ).scalar_one()
            await s.execute(
                text(
                    "insert into eval_case_results (id, run_id, case_name, created_at, updated_at, "
                    "created_by, updated_by) values (gen_random_uuid(), :r, 'v351 케이스', now(), now(), "
                    "'system', 'system')"
                ),
                {"r": run_id},
            )
        await s.execute(
            text(
                "insert into batch_runs (id, job_name, status, dry_run, started_at, created_at, "
                "updated_at, created_by, updated_by) values (gen_random_uuid(), :j, 'ok', false, :t, "
                "now(), now(), 'system', 'system')"
            ),
            {"j": f"{MARK}-old", "t": old},
        )
        await s.execute(
            text(
                "insert into batch_runs (id, job_name, status, dry_run, started_at, created_at, "
                "updated_at, created_by, updated_by) values (gen_random_uuid(), :j, 'ok', false, :t, "
                "now(), now(), 'system', 'system')"
            ),
            {"j": f"{MARK}-recent", "t": recent},
        )
        await s.execute(
            text(
                "insert into memory_snapshots (id, user_id, mem_id, text, created_at, updated_at, "
                "created_by, updated_by) values (gen_random_uuid(), :u, :m, 'v351', :t, now(), "
                "'system', 'system')"
            ),
            {"u": f"{MARK}-u", "m": f"{MARK}-m", "t": old},
        )
        await s.commit()
    return str(ds_id)


async def _count(sql: str) -> int:
    async with SessionLocal() as s:
        return (await s.execute(text(sql))).scalar_one()


async def _teardown(ds_id: str) -> None:
    async with SessionLocal() as s:
        await s.execute(text("delete from eval_datasets where id = :d"), {"d": ds_id})
        await s.execute(text("delete from batch_runs where job_name like :p"), {"p": f"{MARK}%"})
        await s.execute(
            text("delete from memory_snapshots where user_id like :p"), {"p": f"{MARK}%"}
        )
        await s.commit()


async def main() -> None:
    ds_id = await _setup()
    runs_q = f"select count(*) from eval_runs where dataset_id = '{ds_id}'"
    results_q = (
        f"select count(*) from eval_case_results r join eval_runs u on r.run_id = u.id "
        f"where u.dataset_id = '{ds_id}'"
    )
    batch_old_q = f"select count(*) from batch_runs where job_name = '{MARK}-old'"
    batch_recent_q = f"select count(*) from batch_runs where job_name = '{MARK}-recent'"
    snaps_q = f"select count(*) from memory_snapshots where user_id = '{MARK}-u'"

    before_runs = await _count(runs_q)
    before_results = await _count(results_q)
    check(
        before_runs == 13 and before_results == 13,
        f"준비: 런 13 · 결과 13 (got {before_runs}/{before_results})",
    )

    # H4 dry-run
    dry = await cleanup_history(dry_run=True)
    check(
        await _count(runs_q) == 13 and dry.get("would_delete", 0) >= 3,
        f"H4 dry-run은 집계만 (would_delete={dry.get('would_delete')}, by_table={dry.get('by_table')})",
    )

    # 실행
    res = await cleanup_history(dry_run=False)
    after_runs = await _count(runs_q)
    after_results = await _count(results_q)
    check(
        after_runs == 10,
        f"H2 **문제집별 최근 10런은 나이와 무관하게 보존**(추세 앵커) — 13 → {after_runs} (기대 10)",
    )
    check(
        after_results == after_runs,
        f"H1 eval_case_results가 CASCADE로 함께 회수(고아 0) — 결과 {after_results}행 = 런 {after_runs}행",
    )
    check(
        await _count(batch_old_q) == 0 and await _count(batch_recent_q) == 1,
        "H3a 오래된 batch_runs 삭제 · 최근 것은 보존(청소부의 발자국도 치운다)",
    )
    check(await _count(snaps_q) == 0, "H3b 오래된 memory_snapshots 삭제")

    # H5 바닥
    async with SessionLocal() as s:
        await s.execute(text("update batch_config set history_retention_days = 0"))
        await s.commit()
    floor = await cleanup_history(dry_run=False)
    check(
        floor.get("status") == "disabled" and await _count(runs_q) == 10,
        f"H5 보존기간<1이면 잡 비활성(delete-all 금지) (status={floor.get('status')!r})",
    )
    async with SessionLocal() as s:
        await s.execute(text("update batch_config set history_retention_days = 90"))
        await s.commit()

    await _teardown(ds_id)
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY351_OK — {passed}건 전부 통과 (삭제 {res.get('by_table')})")


asyncio.run(main())
