"""배치 작업 함수 — 모두 idempotent, mem0 미접촉. 스펙 038.

각 작업은 `async def job(*, dry_run: bool) -> dict` 시그니처. 결과 dict를 runner가 BatchRun.summary로
박제한다. 작업은 자체 SessionLocal로 DB를 다룬다(요청 컨텍스트 밖에서도 돌아야 하므로).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from ..db import SessionLocal
from ..models import BatchConfig, Session

log = logging.getLogger("api.batch.jobs")


async def _get_config(session) -> BatchConfig:
    """싱글톤 BatchConfig 1행 확보(없으면 생성). 값은 기본 NULL."""
    cfg = (await session.execute(select(BatchConfig).limit(1))).scalars().first()
    if cfg is None:
        cfg = BatchConfig()
        session.add(cfg)
        await session.flush()
    return cfg


async def cleanup_sessions(*, dry_run: bool) -> dict:
    """오래된 세션 정리 — `last_activity < now() - retention_days`. 메시지는 FK ondelete CASCADE로
    DB가 자동 삭제한다(messages.session_pk).

    - 보존창(session_retention_days)이 NULL이면 no-op(disabled) — 명시 설정 전엔 절대 삭제 안 함.
    - 나이 기준 삭제라 자연히 idempotent(이미 지워진 행은 다시 못 찾음).
    - mem0 장기기억(별 저장소, user_id/run_id 키)은 건드리지 않는다 — 전사 ≠ 장기기억(#6은 039).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        days = cfg.session_retention_days
        # 비활성: NULL은 명시 미설정. days<1(0/음수)도 비활성으로 막는다 — days=0이면 cutoff=now()라
        # 모든 세션이 대상이 되는 delete-all 푸트건이 된다. API에서도 ge=1로 거르지만 삭제 지점에서
        # 한 겹 더(방어적). 설정값이 잘못돼도 절대 전체 삭제로 번지지 않게 한다.
        if days is None or days < 1:
            log.info("session-cleanup: 보존창 비활성(days=%s) → no-op", days)
            return {"status": "disabled", "deleted": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            await session.execute(
                select(Session.id, Session.session_id).where(Session.last_activity < cutoff)
            )
        ).all()
        ids = [r[0] for r in rows]

        if dry_run:
            log.info("session-cleanup DRY-RUN: 대상 %d건 (cutoff=%s)", len(ids), cutoff.isoformat())
            return {
                "status": "dry_run",
                "retention_days": days,
                "cutoff": cutoff.isoformat(),
                "would_delete": len(ids),
                "sample": [r[1] for r in rows[:20]],
            }

        if ids:
            # Core bulk DELETE — ORM cascade는 안 걸리지만 messages FK가 ondelete CASCADE라 DB가 정리.
            await session.execute(delete(Session).where(Session.id.in_(ids)))
            await session.commit()
        log.info("session-cleanup: %d건 삭제 (cutoff=%s)", len(ids), cutoff.isoformat())
        return {
            "status": "ok",
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "deleted": len(ids),
        }


# 작업 레지스트리 — CLI choices·API 트리거·스케줄러가 공유하는 단일 출처.
JOBS = {
    "session-cleanup": cleanup_sessions,
}
