"""격리 배치 서비스의 상주 진입점 — 내부 APScheduler. 스펙 038.

자체 프로세스로 돌며(API 앱·호스트 OS와 무관) BatchConfig의 cron식을 읽어 작업을 등록한다.
cron이 NULL이면 미등록(아무 것도 자동 발화하지 않음). k8s Deployment 1파드로 띄우는 모드.
스케줄을 오케스트레이터(k8s CronJob)에 맡기려면 이 대신 `batch run <job>`을 쓴다.
"""

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from ..db import SessionLocal
from ..models import BatchConfig
from .runner import run_job

log = logging.getLogger("api.batch.service")


def _register(scheduler: AsyncIOScheduler, job: str, cron: str | None) -> None:
    """cron이 있으면 작업을 등록, NULL이면 미등록(아무 것도 자동 발화 안 함)."""
    if cron:
        scheduler.add_job(
            run_job,
            CronTrigger.from_crontab(cron),
            args=[job],
            kwargs={"dry_run": False},
            id=job,
            replace_existing=True,
        )
        log.info("%s 스케줄 등록: %s", job, cron)
    else:
        log.info("%s cron 미설정(NULL) → 자동 스케줄 없음", job)


async def _load_schedules(scheduler: AsyncIOScheduler) -> None:
    async with SessionLocal() as session:
        cfg = (await session.execute(select(BatchConfig).limit(1))).scalars().first()
    _register(scheduler, "session-cleanup", cfg.session_cleanup_cron if cfg else None)
    _register(scheduler, "memory-consolidation", cfg.memory_consolidation_cron if cfg else None)


async def serve() -> None:
    scheduler = AsyncIOScheduler()
    await _load_schedules(scheduler)
    scheduler.start()
    log.info("배치 서비스 기동 — 등록 작업 %d개", len(scheduler.get_jobs()))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # 일부 플랫폼 미지원
            pass
    await stop.wait()
    log.info("배치 서비스 종료 신호 — 셧다운")
    scheduler.shutdown(wait=False)
