"""배치 스케줄러 — 상주 진입점 + **인프로세스 리더**(스펙 038 → 348).

**스펙 348이 고친 것**: cron 설정은 있는데 그걸 읽어 실행할 프로세스를 아무도 안 켰다
(`batch_runs` 0행 = 이 서비스가 생긴 이래 배치가 **한 번도 안 돌았다**). 청소 잡을 아무리 잘 만들어도
**손이 없으면 죽은 코드**다. 이제 API lifespan이 스케줄러를 켠다(`BATCH_SCHEDULER=inproc`, 기본).

**advisory lock이 핵심**: 워커·레플리카가 여럿이어도 **정확히 하나만** 스케줄러가 된다. 락을 못 잡은
프로세스는 잡을 등록하지 않는다 — 크론 이중 발화(같은 삭제 잡이 N번 실행)를 구조적으로 막는다.
락 보유 프로세스가 죽으면 세션 종료로 락이 자동 해제되고, 남은 프로세스가 **주기 재시도**로 승계한다
("한 번 실패하면 영영 스케줄러 없음"이 되지 않게).

별도 프로세스 운영(`uv run batch serve`)도 그대로 지원한다 — 그쪽도 같은 락을 잡으므로 앱과 동시에
켜도 이중 발화가 없다(먼저 잡은 쪽이 리더).
"""

import asyncio
import contextlib
import logging
import os
import signal
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text

from ..db import SessionLocal, engine
from ..models import BatchConfig
from .runner import run_job

log = logging.getLogger("api.batch.service")

# advisory lock 키 — 배치 스케줄러 리더 선출용(임의 상수, 다른 락과 겹치지 않게 고정).
_LOCK_KEY = 0x6D7961_6231  # 'mya' + b1
_RETRY_SECONDS = 60

# 스케줄러 상태(관측 표면 — 안 돌면 화면이 그렇게 말한다, 스펙 348)
_state: dict[str, Any] = {"mode": "off", "leader": False, "jobs": []}
_scheduler: AsyncIOScheduler | None = None
_lock_conn: Any = None  # 락을 쥔 커넥션(프로세스 수명 동안 유지 — 놓으면 락도 풀린다)
_task: asyncio.Task | None = None


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
    _register(scheduler, "checkpoint-cleanup", cfg.checkpoint_cleanup_cron if cfg else None)
    _register(scheduler, "token-cleanup", cfg.token_cleanup_cron if cfg else None)
    _register(scheduler, "approval-cleanup", cfg.approval_cleanup_cron if cfg else None)
    _register(scheduler, "history-cleanup", cfg.history_cleanup_cron if cfg else None)
    _register(scheduler, "memory-cleanup", cfg.memory_cleanup_cron if cfg else None)


async def _try_become_leader() -> bool:
    """advisory lock을 잡으면 리더(스케줄러 1개 보장). 커넥션을 **붙들고 있어야** 락이 유지된다."""
    global _lock_conn
    if _lock_conn is not None:
        return True
    conn = await engine.connect()
    got = (
        await conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY})
    ).scalar_one()
    if not got:
        await conn.close()
        return False
    _lock_conn = conn
    return True


def _snapshot_jobs() -> list[dict]:
    if _scheduler is None:
        return []
    return [
        {"name": j.id, "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None}
        for j in _scheduler.get_jobs()
    ]


async def _leader_loop() -> None:
    """리더가 될 때까지 주기 재시도 → 리더가 되면 스케줄러 기동. 승계 경로(리더 사망 시)도 이 루프다."""
    global _scheduler
    while True:
        try:
            if await _try_become_leader():
                _scheduler = AsyncIOScheduler()
                await _load_schedules(_scheduler)
                _scheduler.start()
                _state.update(leader=True, jobs=_snapshot_jobs())
                log.info("배치 스케줄러 리더 — 등록 작업 %d개", len(_scheduler.get_jobs()))
                return
            log.info(
                "배치 스케줄러: 다른 프로세스가 리더 — %d초 후 재시도(승계 대기)", _RETRY_SECONDS
            )
        except Exception as exc:  # DB 미준비 등 — 재시도(부팅을 죽이지 않는다)
            log.warning("배치 스케줄러 리더 시도 실패(재시도): %s", exc)
        await asyncio.sleep(_RETRY_SECONDS)


async def start_inproc() -> None:
    """API lifespan에서 호출 — 앱과 같은 프로세스에서 스케줄러를 켠다(스펙 348).

    `BATCH_SCHEDULER=off`면 켜지 않는다(별도 `batch serve` 프로세스로 운영하는 경우).
    """
    global _task
    mode = os.environ.get("BATCH_SCHEDULER", "inproc").strip().lower()
    _state["mode"] = mode
    if mode != "inproc":
        log.info("배치 스케줄러 인프로세스 비활성(BATCH_SCHEDULER=%s)", mode)
        return
    _task = asyncio.create_task(_leader_loop())


async def stop_inproc() -> None:
    """lifespan 종료 — 스케줄러 정지 + 락 해제(다른 프로세스가 즉시 승계할 수 있게)."""
    global _scheduler, _lock_conn, _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    if _lock_conn is not None:
        with contextlib.suppress(Exception):
            await _lock_conn.close()  # 세션 종료 = advisory lock 해제
        _lock_conn = None
    _state.update(leader=False, jobs=[])


async def reload_schedules() -> bool:
    """설정(cron) 변경을 **즉시** 반영한다 — 리더일 때만(스펙 348).

    이게 없으면 관리자가 화면에서 cron을 바꿔도 다음 재시작까지 안 먹는다("설정은 켰는데 안 돎"의
    또 다른 형태). 리더가 아니면 무동작(반영은 리더 프로세스가 한다).
    """
    if _scheduler is None:
        return False
    await _load_schedules(_scheduler)
    _state["jobs"] = _snapshot_jobs()
    log.info("배치 스케줄 재적재 — 등록 작업 %d개", len(_scheduler.get_jobs()))
    return True


def status() -> dict:
    """스케줄러 상태(관측 표면) — 안 돌고 있으면 **화면이 그렇게 말한다**(조용한 무동작 금지)."""
    return {"mode": _state["mode"], "leader": _state["leader"], "jobs": _snapshot_jobs()}


async def serve() -> None:
    """별도 프로세스 상주 모드(`uv run batch serve`) — 같은 advisory lock을 쓴다(이중 발화 없음)."""
    await _leader_loop()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # 일부 플랫폼 미지원
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    log.info("배치 서비스 종료 신호 — 셧다운")
    await stop_inproc()
