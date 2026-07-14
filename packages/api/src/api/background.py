"""fire-and-forget 백그라운드 태스크의 참조 보관(RUF006) — GC 조기 수거 방지."""

import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger(__name__)

_TASKS: set[asyncio.Task] = set()


def _reap(task: asyncio.Task) -> None:
    """완료 시 참조 해제 + 삼켜질 뻔한 예외를 로그로 표면화(codex 334 P2) — spawn된 잡이
    자체 except 그물 밖에서 죽으면 어디에도 안 보이던 것을 최소한 로그로 남긴다."""
    _TASKS.discard(task)
    if not task.cancelled():
        exc = task.exception()
        if exc is not None:
            logger.error("배경 태스크 미처리 예외: %r", exc, exc_info=exc)


def spawn(coro: Coroutine) -> asyncio.Task:
    """참조를 보관하는 create_task — 완료 시 자동 해제 + 예외 표면화."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_reap)
    return task
