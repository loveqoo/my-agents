"""스펙 067 브라우저 rung 시더 — member 소유 세션 1 + 타인 세션 1(+메시지)을 직접 삽입/삭제.

  seed <member_email>  : agt-067shot + sess-067shot-own(member auth id 소유) + sess-067shot-other
                         (임의 user_id 소유) + 각 user 메시지 1건.
  unseed               : sess-067shot* + agt-067shot 삭제.

member의 세션 뷰가 *자기 것만*(own) 보이고 타인(other)은 숨는지 브라우저로 확인하기 위한 합성 데이터.
실행(packages/api 기준): uv run python tests/_seed_session_067.py seed <email>
"""
import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import delete, select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.models import Agent, Message, Session, User  # noqa: E402

AGENT_ID = "agt-067shot"
PREFIX = "sess-067shot-"
OWN = f"{PREFIX}own"
OTHER = f"{PREFIX}other"


async def _seed(email: str) -> None:
    email = (email or "").strip().lower()
    async with SessionLocal() as s:
        member_id = (
            await s.execute(select(User.id).where(User.email == email))
        ).scalar_one_or_none()
        if member_id is None:
            print("SEED_FAIL(유저 없음):", email)
            sys.exit(2)
        agent = Agent(agent_id=AGENT_ID, name="probe067shot", source="ui")
        s.add(agent)
        await s.flush()
        for sid, owner, msg in [
            (OWN, str(member_id), "내 비밀 대화"),
            (OTHER, str(uuid.uuid4()), "남의 비밀 대화"),
        ]:
            sess = Session(session_id=sid, agent_pk=agent.id, agent_name="probe067shot",
                           user_id=owner, status="active")
            s.add(sess)
            await s.flush()
            s.add(Message(session_pk=sess.id, role="user", content=msg))
        await s.commit()
    print("SEED_OK", OWN, OTHER)


async def _unseed() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(Session).where(Session.session_id.like(f"{PREFIX}%")))
        await s.execute(delete(Agent).where(Agent.agent_id == AGENT_ID))
        await s.commit()
    print("UNSEED_OK")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: _seed_session_067.py {seed <email> | unseed}")
        sys.exit(1)
    if sys.argv[1] == "seed":
        if len(sys.argv) < 3:
            print("seed는 member email이 필요합니다")
            sys.exit(1)
        asyncio.run(_seed(sys.argv[2]))
    elif sys.argv[1] == "unseed":
        asyncio.run(_unseed())
    else:
        print("미지의 명령:", sys.argv[1])
        sys.exit(1)


if __name__ == "__main__":
    main()
