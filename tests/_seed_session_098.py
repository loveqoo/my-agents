"""스펙 098 브라우저 검증용 마커 세션 시드/정리. `seed` | `clean` 인자.

브라우저에서 검색어 `ZZBROWSERMARK098`로 좁혀 2건만 남는지 눈+구조로 확인하기 위한 픽스처.
자가정리(prefix sess_zz098_). 실행: .venv/bin/python tests/_seed_session_098.py seed|clean
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api.models import Agent, Session  # noqa: E402

PREFIX = "sess_zz098_"
MARK = "ZZBROWSERMARK098"


async def seed() -> None:
    async with async_session() as sess:
        await sess.execute(delete(Session).where(Session.session_id.like(f"{PREFIX}%")))
        agent = (await sess.execute(select(Agent).limit(1))).scalar_one_or_none()
        if agent is None:
            raise RuntimeError("시드 불가: agents 비어있음")
        now = datetime.now(timezone.utc)
        for i, tag in enumerate(("a", "b")):
            sess.add(Session(
                session_id=f"{PREFIX}{tag}",
                agent_pk=agent.id,
                agent_name=MARK,
                status="active",
                started_at=now - timedelta(seconds=i),
                last_activity=now - timedelta(seconds=i),
            ))
        await sess.commit()
    print(f"SEEDED 2 sessions (agent_name={MARK})")


async def clean() -> None:
    async with async_session() as sess:
        await sess.execute(delete(Session).where(Session.session_id.like(f"{PREFIX}%")))
        await sess.commit()
    print("CLEANED")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    asyncio.run(seed() if mode == "seed" else clean())
