"""fire-and-forget 백그라운드 태스크의 참조 보관(RUF006) — GC 조기 수거 방지."""

import asyncio
from collections.abc import Coroutine

_TASKS: set[asyncio.Task] = set()


def spawn(coro: Coroutine) -> asyncio.Task:
    """참조를 보관하는 create_task — 완료 시 자동 해제."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task
