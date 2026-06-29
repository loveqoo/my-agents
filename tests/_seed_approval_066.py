"""스펙 066 브라우저 샷용 합성 Approval 시더 — owner(member) 소유 pending 행 1개를 넣고/지운다.

브라우저 rung은 member가 *자기* 승인 행을 UI에서 보고(스코핑), resolve 시 403 detail이 토스트로
도달하는지 본다. 그 전제 행을 chat 흐름 없이 직접 주입한다(실 데이터 무오염, apr-066shot* prefix).

사용:
  seed <member_email> [permission]   member UUID 조회 후 pending Approval 주입, approval_id 출력
  unseed                              apr-066shot* 전부 삭제
실행: uv run python tests/_seed_approval_066.py seed user@example.com data.delete
"""
import asyncio
import sys

from sqlalchemy import delete, select

from api.db import SessionLocal
from api.models import Approval, User

PREFIX = "apr-066shot"


async def _seed(email: str, permission: str) -> None:
    async with SessionLocal() as s:
        uid = (await s.execute(select(User.id).where(User.email == email))).scalar_one()
        s.add(Approval(
            approval_id=PREFIX, session_id="sess-066shot", user_id=str(uid),
            agent_pk=None, agent_name="probe066", permission=permission,
            action=f"{permission}.action", args={"target": "row-42"},
            summary="민감 작업: 레코드 삭제 요청", checkpoint="ckpt-066shot",
            status="pending",
        ))
        await s.commit()
    print(PREFIX)


async def _unseed() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(Approval).where(Approval.approval_id.like(f"{PREFIX}%")))
        await s.commit()
    print("unseeded")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "seed":
        asyncio.run(_seed(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "data.delete"))
    elif cmd == "unseed":
        asyncio.run(_unseed())
    else:
        print("usage: seed <email> [permission] | unseed", file=sys.stderr)
        sys.exit(2)
