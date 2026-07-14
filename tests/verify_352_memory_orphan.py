"""verify_352 — mem0 도달 불가 기억(유령) 회수 (스펙 352 — 캠페인 마지막 누수 테이블).

이 검증의 무게중심은 **지우는 것**이 아니라 **안 지우는 것**이다. 기억은 제품의 토대 기능이라,
살아있는 유저의 기억을 한 행이라도 지우면 회수가 기능을 죽인다(스펙 351의 교훈).

  M1 죽은 유저의 기억 삭제 · **살아있는 유저의 기억은 0건 삭제**(같은 나이여도).
  M2 user_id가 죽었어도 **run_id(세션)나 agent_id가 살아 있으면 보존** — 한 축이라도 살아 있으면
     회상 가능하므로 유령이 아니다.
  M3 유예 기간 내 행은 0건 삭제(세션 행이 없는 살아있는 대화 보호).
  M4 created_at 불명 행은 0건 삭제(나이를 모르면 안 지운다).
  M5 dry-run은 세기만 하고 삭제 0.
  M6 유예 <1이면 잡 비활성(delete-all 금지).
  M7 삭제가 판정과 **한 문장** — 그 사이에 소유자가 되살아나도 안 지운다(codex P1 TOCTOU).

실행: uv run python tests/verify_352_memory_orphan.py
"""

import asyncio
import json
import pathlib
import sys
import uuid
from datetime import UTC, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api.batch.jobs import cleanup_memories  # noqa: E402
from api.memory import reclaim  # noqa: E402
from api.db import SessionLocal  # noqa: E402

MARK = f"v352-{uuid.uuid4().hex[:6]}"
_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


OLD = (datetime.now(UTC) - timedelta(days=30)).isoformat()
FRESH = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
_dim: int | None = None  # mem0 벡터 차원 — 하드코딩하지 않고 **DB에서 읽는다**(모델 바뀌면 같이 바뀜)


async def _plant(tag: str, payload: dict) -> None:
    """mem0_memories에 합성 행 1개(벡터는 0벡터 — 검색이 아니라 회수 판정만 검증)."""
    global _dim
    payload = {"data": f"{MARK} {tag}", **payload}
    async with SessionLocal() as s:
        if _dim is None:
            _dim = (
                await s.execute(
                    text(
                        "select atttypmod from pg_attribute where attrelid = 'mem0_memories'::regclass "
                        "and attname = 'vector'"
                    )
                )
            ).scalar_one()
        vec = "[" + ",".join(["0"] * _dim) + "]"
        await s.execute(
            text(  # noqa: S608 — 상수 테이블명 + 0벡터 리터럴
                f"insert into mem0_memories (id, vector, payload) "
                f"values (gen_random_uuid(), '{vec}'::vector, cast(:p as jsonb))"
            ),
            {"p": json.dumps(payload)},
        )
        await s.commit()


async def _alive() -> tuple[str, str, str]:
    """살아있는 유저·세션·에이전트를 DB에서 하나씩 집는다(합성 아님 — 실제 소유자여야 의미가 있다)."""
    async with SessionLocal() as s:
        uid = (await s.execute(text('select id::text from "user" limit 1'))).scalar_one()
        sid = (await s.execute(text("select session_id from sessions limit 1"))).scalar_one_or_none()
        aid = (await s.execute(text("select agent_id from agents limit 1"))).scalar_one()
    return uid, sid or "", aid


async def _left(tag: str) -> int:
    async with SessionLocal() as s:
        return (
            await s.execute(
                text("select count(*) from mem0_memories where payload->>'data' = :d"),
                {"d": f"{MARK} {tag}"},
            )
        ).scalar_one()


async def _wipe() -> None:
    async with SessionLocal() as s:
        await s.execute(
            text("delete from mem0_memories where payload->>'data' like :p"), {"p": f"{MARK}%"}
        )
        await s.commit()


async def main() -> None:
    await _wipe()
    live_user, live_session, live_agent = await _alive()
    dead = str(uuid.uuid4())  # user 테이블에 없는 uuid
    if not live_session:
        print("  (참고) sessions 행이 없어 run_id 축 보존 케이스는 합성 세션으로 대체할 수 없다 — 스킵")

    # --- 심는다
    await _plant("ghost-user", {"user_id": dead, "created_at": OLD})  # 유령: 죽은 유저
    await _plant("ghost-all", {"user_id": dead, "run_id": "sess-없음", "agent_id": "agt-없음", "created_at": OLD})
    await _plant("live-user", {"user_id": live_user, "created_at": OLD})  # 살아있는 유저(같은 나이!)
    await _plant("live-agent", {"user_id": dead, "agent_id": live_agent, "created_at": OLD})  # 축 하나 생존
    if live_session:
        await _plant("live-session", {"user_id": dead, "run_id": live_session, "created_at": OLD})
    await _plant("fresh", {"user_id": dead, "created_at": FRESH})  # 유예 기간 내
    await _plant("no-ts", {"user_id": dead})  # 나이 불명

    # --- M5 dry-run
    dry = await cleanup_memories(dry_run=True)
    still = await _left("ghost-user")
    check(
        dry.get("would_delete", 0) >= 2 and still == 1,
        f"M5 dry-run은 집계만 (would_delete={dry.get('would_delete')}, 유령 잔존={still})",
    )

    # --- 실행
    res = await cleanup_memories(dry_run=False)
    check(
        await _left("ghost-user") == 0 and await _left("ghost-all") == 0,
        f"M1a 죽은 소유자의 기억(유령) 삭제 (deleted={res.get('deleted')})",
    )
    check(
        await _left("live-user") == 1,
        "M1b **살아있는 유저의 기억은 0건 삭제** — 같은 나이(30일)여도 지우지 않는다",
    )
    check(await _left("live-agent") == 1, "M2a user_id가 죽어도 agent_id가 살아 있으면 보존(회상 가능)")
    if live_session:
        check(
            await _left("live-session") == 1, "M2b user_id가 죽어도 run_id(세션)가 살아 있으면 보존"
        )
    check(await _left("fresh") == 1, "M3 유예 기간 내 행은 보존(세션 행 없는 살아있는 대화 보호)")
    check(await _left("no-ts") == 1, "M4 created_at 불명 행은 보존(나이를 모르면 안 지운다)")

    # --- M6 바닥
    async with SessionLocal() as s:
        await s.execute(text("update batch_config set memory_orphan_grace_days = 0"))
        await s.commit()
    floor = await cleanup_memories(dry_run=False)
    check(
        floor.get("status") == "disabled" and await _left("live-user") == 1,
        f"M6 유예<1이면 잡 비활성(delete-all 금지) (status={floor.get('status')!r})",
    )
    async with SessionLocal() as s:
        await s.execute(text("update batch_config set memory_orphan_grace_days = 7"))
        await s.commit()

    # --- M7 TOCTOU 핀(codex P1): 삭제 SQL이 **자기 안에서** 도달 불가 조건을 재평가해야 한다.
    # `SELECT id` → `DELETE WHERE id = ANY(:ids)`로 나누면, 그 사이에 유저/세션/에이전트가 되살아난
    # 기억을 **되살아난 뒤에** 지운다. 구조가 되돌아가면 이 핀이 깨진다.
    sql = reclaim._DELETE_BATCH
    check(
        "NOT EXISTS" in sql and "ANY(:ids)" not in sql and "RETURNING id" in sql,
        "M7 삭제가 판정과 한 문장(TOCTOU) — 조건 재평가 + RETURNING으로 실제 rowcount",
    )

    await _wipe()
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY352_OK — {passed}건 전부 통과")


asyncio.run(main())
