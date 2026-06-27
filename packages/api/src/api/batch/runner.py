"""배치 runner — 작업 1회 실행을 BatchRun으로 박제(시작 running → ok/error). 스펙 038.

작업 예외는 박제하고 graceful 결과를 반환한다(상주 서비스를 죽이지 않음). 미지 작업명은 ValueError.
"""

import logging
from datetime import datetime, timezone

from ..db import SessionLocal
from ..models import BatchRun
from .jobs import JOBS

log = logging.getLogger("api.batch.runner")

# 감사행(BatchRun.summary)에 영속하지 않는 미리보기 전용 키 — 라이브 응답에는 남기되 장기 감사
# 테이블엔 원시 식별자를 쌓지 않는다(데이터 최소화). 예: dry-run의 sample(세션 식별자 목록)은
# 운영자 즉시 미리보기엔 유용하나, 삭제된 세션 식별자를 감사행에 무기한 남길 이유는 없다.
_AUDIT_OMIT_KEYS = ("sample",)


def _scrub(obj):
    """'sample' 키를 어느 깊이에서든 제거 — 미리보기 전용 데이터는 감사행에 영속하지 않는다.
    재귀: 038의 세션정리 dry-run은 top-level sample(세션 식별자), 039의 통합 dry-run은
    candidates[].sample(제안된 사실 본문)을 가진다. 둘 다 라이브 응답엔 남기되 감사엔 미적재."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in _AUDIT_OMIT_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _audit_summary(summary: dict | None) -> dict | None:
    """감사행에 박제할 summary — 미리보기 전용 키(sample)를 재귀 제거한 사본."""
    if not summary:
        return summary
    return _scrub(summary)


async def run_job(name: str, *, dry_run: bool = False) -> dict:
    job = JOBS.get(name)
    if job is None:
        raise ValueError(f"미지의 배치 작업: {name!r} (가능: {sorted(JOBS)})")

    # 시작 행 박제(별 트랜잭션 — 작업이 죽어도 running 흔적이 남음).
    async with SessionLocal() as session:
        run = BatchRun(job_name=name, status="running", dry_run=dry_run)
        session.add(run)
        await session.commit()
        run_id = run.id

    try:
        # run_id 전달 — 작업이 자기 실행을 감사 데이터에 링크할 수 있게(예: MemorySnapshot.batch_run_id,
        # 스펙 039). 쓰지 않는 작업(session-cleanup)은 run_id=None 기본으로 무시한다.
        summary = await job(dry_run=dry_run, run_id=run_id)
        status, error = "ok", None
    except Exception as e:  # noqa: BLE001 — 실패도 박제하고 graceful 반환
        log.exception("배치 작업 실패: %s", name)
        summary, status, error = None, "error", f"{type(e).__name__}: {e}"

    # 종료 상태 박제.
    async with SessionLocal() as session:
        run = await session.get(BatchRun, run_id)
        if run is not None:
            run.status = status
            run.summary = _audit_summary(summary)  # 미리보기 키(sample 등)는 감사행에 미영속
            run.error = error
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()

    result = {"run_id": str(run_id), "job": name, "status": status}
    if summary is not None:
        result["summary"] = summary
    if error is not None:
        result["error"] = error
    return result
