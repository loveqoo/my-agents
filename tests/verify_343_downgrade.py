"""verify_343b — 마이그레이션 왕복(upgrade → downgrade → upgrade) (스펙 343, codex P1).

codex가 짚은 P1: downgrade가 개명을 먼저 되돌리면 message_feedback에 감사 created_by가 아직 남아
있어 충돌한다. **다운그레이드는 아무도 안 돌려봐서 조용히 썩는다** — 왕복을 상주 핀으로 박는다.

  D1 upgrade(head) 후: message_feedback에 owner_id + 감사 4컬럼 공존.
  D2 downgrade -1: 감사 컬럼 사라지고 created_by(구 이름)로 복귀, owner_id 없음.
  D3 재upgrade: 다시 head — 왕복이 멱등(운영에서 되돌릴 수 있다는 실증).

실행: uv run python tests/_throwaway_db.py tests/verify_343_downgrade.py   (virgin DB)
"""

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "packages" / "api" / "src"))

from alembic import command  # noqa: E402
from sqlalchemy import text  # noqa: E402

from api.db import SessionLocal, _alembic_config, init_db  # noqa: E402

REV = "a7f3c9e21b4d"
PREV = "d5795d21f6a2"
_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def _cols(table: str) -> set[str]:
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema='public' and table_name=:t"
                ),
                {"t": table},
            )
        ).all()
    return {r[0] for r in rows}


def _sync(fn, *a):  # alembic은 동기 API — 이벤트 루프 밖 스레드에서
    return asyncio.get_event_loop().run_in_executor(None, fn, *a)


async def main() -> None:
    await init_db()  # head까지 upgrade
    cfg = _alembic_config()

    c = await _cols("message_feedback")
    check({"owner_id", "created_at", "updated_at", "created_by", "updated_by"} <= c,
          f"D1 upgrade 후 owner_id + 감사 4컬럼 공존 (got {sorted(c & {'owner_id','created_by','updated_by'})})")

    await _sync(command.downgrade, cfg, PREV)  # 감사 컬럼 제거 + 개명 복귀
    c2 = await _cols("message_feedback")
    check("created_by" in c2 and "owner_id" not in c2 and "updated_by" not in c2,
          f"D2 downgrade = 감사 컬럼 제거·created_by(구 이름) 복귀 (got {sorted(c2)})")
    c2p = await _cols("personas")
    check(not ({"created_by", "updated_by"} & c2p), f"D2b 다른 테이블도 감사 컬럼 제거 (personas: {sorted(c2p)})")

    await _sync(command.upgrade, cfg, REV)  # 재적용(멱등)
    c3 = await _cols("message_feedback")
    check({"owner_id", "created_by", "updated_by"} <= c3, f"D3 재upgrade 성공(왕복 멱등) (got {sorted(c3 & {'owner_id','created_by','updated_by'})})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY343B_OK — {passed}건 전부 통과")


asyncio.run(main())
