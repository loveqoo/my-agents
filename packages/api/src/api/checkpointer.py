"""HIL durable 체크포인터 — AsyncPostgresSaver 싱글턴 (스펙 041, P5-a).

langgraph가 소유하는 테이블(`checkpoints`/`checkpoint_writes`/`checkpoint_blobs`/`checkpoint_migrations`)을
공유 Postgres에 멱등 생성(`.setup()`)하고, 그래프 재구축 시 **같은 인스턴스**를 주입해
interrupt→일시정지→재개를 durable하게 만든다. 우리 `Base.metadata` 밖(라이브러리 소유) → alembic 무관.

**왜 durable(MemorySaver 아님):** 위험 도구 호출이 그래프를 멈추면 그 상태(체크포인트)가 Postgres에
박힌다. admin 승인은 **다른 요청·다른 워커**에서 들어올 수 있으므로, 프로세스 메모리가 아니라 공유
DB에 있어야 한 워커가 박은 일시정지를 다른 워커가 재개할 수 있다.

DSN은 mem0 백엔드의 `_sync_dsn`(asyncpg→psycopg 드라이버 접미사 제거)을 재사용한다 — 그 헬퍼는
순수 문자열 변환이고 mem0 import는 `mem0_backend` 안에서 지연(함수 내부)이라 여기서 끌어와도 mem0를
적재하지 않는다(grep 격리 불변식 유지).
"""

import asyncio
import contextlib
import logging
import os

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .memory.mem0_backend import _sync_dsn

log = logging.getLogger("api.checkpointer")

_saver: AsyncPostgresSaver | None = None
_pool: AsyncConnectionPool | None = None  # 풀 수명 보유(종료 시 close)
_init_lock = asyncio.Lock()  # 재진입 직렬화 — sweep()이 fallback으로 init을 부른다(codex 354 P1)

# langgraph가 전제하는 커넥션 설정 — from_conn_string이 주는 것과 **동일**해야 한다
# (autocommit=True·prepare_threshold=0·row_factory=dict_row). 빠뜨리면 조용히 깨진다.
_CONN_KWARGS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
# 풀 크기: langgraph AsyncPostgresSaver는 내부 self.lock으로 DB 작업을 **직렬화**한다(codex 354 P2).
# 그래서 큰 풀은 처리량을 안 늘리고 idle 커넥션만 예약해 작은 Postgres에서 too-many-connections를
# 부른다. 정확성(단일 커넥션 pipeline 충돌 회피)만 얻으면 되므로 작게: min 1(첫 요청 지연 회피)·max 5.
_POOL_MIN = 1
_POOL_MAX = 5


async def init_checkpointer() -> AsyncPostgresSaver | None:
    """앱 시작(lifespan)에 1회 — **커넥션 풀** 오픈 + langgraph 테이블 멱등 생성. 실패는 graceful(None).

    **왜 풀인가(스펙 354)**: from_conn_string은 단일 커넥션을 열어 싱글턴 공유하는데, 단일 커넥션을
    여러 코루틴(배치 스윕 + 채팅)이 밟으면 "another command in progress / cannot enter pipeline mode"로
    충돌한다(실측 재현). 풀을 주면 각 작업이 자기 커넥션을 빌려 **동시성 안전**해진다(단, saver 내부
    lock 때문에 실제로 병렬 처리되는 건 아니고 큐잉된다 — 얻는 건 처리량이 아니라 pipeline 충돌 회피).

    **재진입 안전(codex 354 P1)**: `sweep()`이 배치 프로세스에서 fallback으로 이 함수를 부르므로 동시
    진입이 가능하다. lock으로 직렬화하고, 로컬 변수로 만든 뒤 **성공했을 때만** 전역에 publish해
    풀 누수·전역 뒤집힘을 막는다.

    DB가 없거나 setup이 실패하면 None을 남기고 경고만 — HIL 게이트는 그때 비활성(승인 게이팅 없이
    기존 무상태 경로로 폴백, chat.py가 checkpointer None을 흡수). 메모리 부재가 채팅을 죽이지 않는
    스펙 019 graceful 원칙과 동형.
    """
    global _saver, _pool
    async with _init_lock:
        if _saver is not None:
            return _saver
        url = os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"
        )
        dsn = _sync_dsn(url)
        pool: AsyncConnectionPool | None = None
        try:
            pool = AsyncConnectionPool(
                conninfo=dsn,
                min_size=_POOL_MIN,
                max_size=_POOL_MAX,
                open=False,
                kwargs=_CONN_KWARGS,
                # checkout 검증(스펙 403): SSE 이탈 취소가 오염시킨 커넥션("another command in
                # progress"·closed)을 빌려주기 전에 검출·교체 — 메인 엔진 pool_pre_ping과 쌍.
                check=AsyncConnectionPool.check_connection,
            )
            await pool.open()
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            _pool, _saver = pool, saver  # 성공 후에만 전역 publish
            log.info("AsyncPostgresSaver 준비 완료(HIL 체크포인터 — 커넥션 풀 max=%d)", _POOL_MAX)
        except Exception as exc:
            log.warning("체크포인터 초기화 실패 — HIL 게이트 비활성: %s", exc)
            if pool is not None:
                with contextlib.suppress(Exception):  # 정리 실패는 삼킨다(초기화 실패 경로)
                    await pool.close()
        return _saver


def get_checkpointer() -> AsyncPostgresSaver | None:
    """현재 싱글턴(미초기화/실패 시 None). 그래프 재구축·재개가 같은 인스턴스를 받게 하는 단일 출처."""
    return _saver


async def close_checkpointer() -> None:
    """앱 종료(lifespan)에 풀 정리."""
    global _saver, _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception as exc:
            log.warning("체크포인터 종료 중 오류(무시): %s", exc)
    _saver = None
    _pool = None
