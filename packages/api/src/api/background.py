"""fire-and-forget 백그라운드 태스크의 참조 보관(RUF006) — GC 조기 수거 방지."""

import asyncio
import logging
from collections.abc import Coroutine

from . import audit

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


async def _as_system(coro: Coroutine) -> object:
    """배경 잡의 감사 actor = system(스펙 343 — 사용자 결정).

    create_task는 **요청의 contextvar를 승계**하므로, 그냥 두면 배경 잡이 요청자 이름으로 행을
    찍는다. 정책을 잡별로 두면 하나 빠뜨린다(codex 343 P2가 인제스트만 처리된 걸 짚음) — 모든
    배경 잡이 통과하는 **이 관문 한 곳**에서 뒤집는다. 요청 경로의 행(예: documents 생성)은 이미
    사용자 actor로 찍힌 뒤다: "누가 시켰나"는 created_by, "누가 처리했나"는 updated_by.
    """
    audit.set_actor(audit.SYSTEM_ACTOR)
    return await coro


def spawn(coro: Coroutine) -> asyncio.Task:
    """참조를 보관하는 create_task — 완료 시 자동 해제 + 예외 표면화 + 감사 actor=system(343)."""
    task = asyncio.create_task(_as_system(coro))
    _TASKS.add(task)
    task.add_done_callback(_reap)
    return task
