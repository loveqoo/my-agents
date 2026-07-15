"""스펙 303 rung 2 — 신선 빈 DB에 실제 스키마+seed_if_empty 후 카운트 측정.

라이브 `agents` DB는 건드리지 않는다. 호출자가 DATABASE_URL을 **일회용 DB**로 지정해 실행하고
끝나면 그 DB를 drop한다(드라이버 스크립트가 생성/삭제 담당). 이 스크립트는:
  1) init_db()로 실제 스키마 구축(alembic upgrade head — 실패는 fail-fast, 스펙 330)
  2) seed_if_empty()로 첫 설치 데이터 적재
  3) 심긴 행을 카운트해 트림 후 정예(프롬프트2·컬렉션3·세션0·에이전트5·승인0)와 대조

실행: DATABASE_URL=<throwaway> uv run python tests/smoke_303_fresh_seed.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

# 안전핀: 라이브 DB 이름으로 실행되면 즉시 중단(파괴 방지).
_url = os.environ.get("DATABASE_URL", "")
if _url.rsplit("/", 1)[-1] == "agents" or "smoke" not in _url:
    print(f"거부: DATABASE_URL이 일회용 DB(...smoke...)가 아님 → {_url!r}")
    sys.exit(2)

from sqlalchemy import func, select  # noqa: E402

from api.db import SessionLocal, init_db  # noqa: E402
from api.models import Agent, Approval, Collection, Prompt, Session  # noqa: E402
from api.seed import seed_if_empty  # noqa: E402

EXPECT = {"Prompt": 2, "Collection": 3, "Session": 0, "Agent": 5, "Approval": 0}
_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def main() -> None:
    await init_db()  # 실제 스키마 경로(alembic head 단일 — 스펙 330)
    async with SessionLocal() as s:
        await seed_if_empty(s)
    async with SessionLocal() as s:
        counts = {}
        for name, model in [
            ("Prompt", Prompt),
            ("Collection", Collection),
            ("Session", Session),
            ("Agent", Agent),
            ("Approval", Approval),
        ]:
            counts[name] = (await s.scalar(select(func.count()).select_from(model))) or 0
        # 심긴 이름도 뽑아 고아 제거를 눈으로 확인.
        pnames = sorted(p for p in (await s.execute(select(Prompt.name))).scalars())
        cnames = sorted(c for c in (await s.execute(select(Collection.name))).scalars())

    print(f"\n심긴 카운트: {counts}")
    print(f"프롬프트: {pnames}")
    print(f"컬렉션:   {cnames}\n")
    for name, exp in EXPECT.items():
        check(counts[name] == exp, f"{name} == {exp} (실제 {counts[name]})")
    check(
        "strict-senior-engineer" not in pnames and "calm-sre" not in pnames, "고아 프롬프트 미적재"
    )
    check("support-tickets" not in cnames, "고아 컬렉션 미적재")

    if _fails:
        print(f"\nFAIL {len(_fails)}건")
        sys.exit(1)
    print("\nPASS — 신선 시드 실측이 트림 후 정예와 일치.")


if __name__ == "__main__":
    asyncio.run(main())
