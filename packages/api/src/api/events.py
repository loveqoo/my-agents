"""배경 잡 이벤트 채널(스펙 335) — 프로세스 내 pub/sub + SSE 스트림.

배경 잡(인제스트 등)의 성공/실패를 **어디서든** 푸시로 알린다(드로어 폴링은 상태의 진실,
이벤트는 알림 겹). 의미론: 구독 전/연결 끊김 동안 발생분은 유실 — 영속 알림함이 아니다.

경계(정직): in-process 버스 — 멀티 파드에선 자기 파드가 처리한 잡만 알린다(k8s 백로그 합류 시
Redis pub/sub 등으로 승격). 단일 프로세스 dev 도구 전제(eval 좀비 스윕과 동일 결).
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .auth import current_principal
from .models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])

# 구독자 큐 집합 — 상한 초과 시 그 구독자의 이벤트만 드롭(no-block: 느린 브라우저 하나가
# 배경 잡을 못 막는다). 발행은 동기·비대기.
_SUBS: set[asyncio.Queue] = set()
_QUEUE_MAX = 100
_HEARTBEAT_SEC = 15
# 동시 구독 상한(codex 335 P2) — 인증 유저 전제여도 탭 방치/스크립트로 fanout O(N)이 무한히
# 크지 않게. 초과는 429(알림은 UX 겹이라 거절해도 기능 손실 없음 — 진실은 문서 status).
_MAX_SUBS = 20


def publish(event: dict) -> None:
    """이벤트 발행(비블로킹) — 배경 잡이 부른다. 구독자 없으면 무동작(알림은 best-effort)."""
    for q in list(_SUBS):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # 느린 구독자 — 이 이벤트만 드롭(상태의 진실은 문서 status라 유실 무해).
            logger.debug("이벤트 구독자 큐 가득 — 드롭: %s", event.get("type"))


def _frame(event: dict) -> str:
    """SSE data 프레임 직렬화(순수 함수) — ensure_ascii=False로 한글 원문."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("")
async def stream_events(
    _principal: User | str = Depends(current_principal),
) -> StreamingResponse:
    """SSE 이벤트 스트림 — 로그인 유저 전용(EventSource는 쿠키 동행). 15초 heartbeat로 연결
    유지, 클라이언트가 끊으면 finally가 구독 해제(누수 없음). EventSource가 자동 재연결한다."""
    if len(_SUBS) >= _MAX_SUBS:
        from fastapi import HTTPException

        raise HTTPException(status_code=429, detail="이벤트 구독이 너무 많습니다 — 잠시 후 재시도")
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)

    async def gen() -> AsyncIterator[str]:
        _SUBS.add(q)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SEC)
                except TimeoutError:
                    yield ": ping\n\n"  # heartbeat — 프록시/브라우저 idle 타임아웃 방지
                    continue
                yield _frame(ev)
        finally:
            _SUBS.discard(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _test_subscribe() -> asyncio.Queue:
    """검증 전용 구독(HTTP 없이 버스 관통) — 프로덕션 코드는 쓰지 않는다."""
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _SUBS.add(q)
    return q


def _test_unsubscribe(q: asyncio.Queue) -> None:
    with contextlib.suppress(KeyError):
        _SUBS.remove(q)
