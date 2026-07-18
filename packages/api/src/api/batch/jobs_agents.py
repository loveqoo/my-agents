"""A2A 정크 에이전트 정리 — jobs.py에서 분할(스펙 395 P4, 순수 이동).

파사드는 jobs.py(재수출 계약). 사설망 판정은 jobs_guards(_is_private_host).
"""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy import func as safunc

from ..db import SessionLocal
from ..models import Agent, Session
from .jobs_guards import _is_private_host

log = logging.getLogger("api.batch.jobs")


async def cleanup_a2a_agents(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — runner가 키워드 호출(계약)
    """A2A 정크 정리(스펙 050, #1) — `source='external'` AND endpoint 호스트가 루프백/RFC1918 사설인
    에이전트 삭제. 테스트가 등록한 프로브 A2A 카드만 걸린다.

    - 바닥: source 비-external(ui/code 데모)은 **절대** 손대지 않음(쿼리에 source 고정). endpoint
      NULL/공개 호스트도 제외. → 규칙이 데모·실 파트너로 번지지 않음(learning 037).
    - cascade: Agent 삭제 → sessions(agent_pk FK ondelete CASCADE)·agent_versions(동일)도 DB가 정리.
      Approval.agent_pk는 SET NULL(고아 무해). dry-run에 딸려 죽을 세션 수를 함께 표기(정직).
    - idempotent: 삭제 후 재실행 deleted=0(매치가 사라짐).
    """
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Agent.id, Agent.agent_id, Agent.name, Agent.endpoint).where(
                    Agent.source == "external", Agent.endpoint.is_not(None)
                )
            )
        ).all()
        # 호스트 판정은 Python(ipaddress)에서 — SQL로 RFC1918 전 범위를 정확히 긋기 어렵다.
        matched = [r for r in rows if _is_private_host(r[3])]
        ids = [r[0] for r in matched]

        # 함께 죽을 세션 수(정직한 cascade 표기).
        session_count = 0
        if ids:
            session_count = (
                await session.execute(
                    select(safunc.count()).select_from(Session).where(Session.agent_pk.in_(ids))
                )
            ).scalar_one()

        meta = {"matched_agents": len(ids), "cascade_sessions": int(session_count)}
        sample = [{"agent_id": r[1], "name": r[2], "endpoint": r[3]} for r in matched[:20]]

        if dry_run:
            log.info("a2a-cleanup DRY-RUN: 대상 %d 에이전트 (+세션 %d)", len(ids), session_count)
            return {"status": "dry_run", **meta, "would_delete": len(ids), "sample": sample}

        if not ids:
            return {"status": "ok", **meta, "deleted": 0}
        # Core bulk DELETE — sessions/agent_versions는 FK ondelete CASCADE라 DB가 정리.
        await session.execute(delete(Agent).where(Agent.id.in_(ids)))
        await session.commit()
        log.info("a2a-cleanup: %d 에이전트 삭제 (+세션 %d cascade)", len(ids), session_count)
        return {"status": "ok", **meta, "deleted": len(ids)}
