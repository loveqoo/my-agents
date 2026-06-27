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

import logging
import os

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from .memory.mem0_backend import _sync_dsn

log = logging.getLogger("api.checkpointer")

_saver: AsyncPostgresSaver | None = None
_cm = None  # from_conn_string이 돌려준 async context manager(풀 수명 보유)


async def init_checkpointer() -> AsyncPostgresSaver | None:
    """앱 시작(lifespan)에 1회 — 풀 오픈 + langgraph 테이블 멱등 생성. 실패는 graceful(None).

    DB가 없거나 setup이 실패하면 None을 남기고 경고만 — HIL 게이트는 그때 비활성(승인 게이팅 없이
    기존 무상태 경로로 폴백, chat.py가 checkpointer None을 흡수). 메모리 부재가 채팅을 죽이지 않는
    스펙 019 graceful 원칙과 동형.
    """
    global _saver, _cm
    if _saver is not None:
        return _saver
    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"
    )
    dsn = _sync_dsn(url)
    try:
        _cm = AsyncPostgresSaver.from_conn_string(dsn)
        _saver = await _cm.__aenter__()
        await _saver.setup()
        log.info("AsyncPostgresSaver 준비 완료(HIL 체크포인터)")
    except Exception as exc:  # noqa: BLE001 — 체크포인터 부재가 앱을 막지 않는다(graceful)
        log.warning("체크포인터 초기화 실패 — HIL 게이트 비활성: %s", exc)
        _saver = None
        _cm = None
    return _saver


def get_checkpointer() -> AsyncPostgresSaver | None:
    """현재 싱글턴(미초기화/실패 시 None). 그래프 재구축·재개가 같은 인스턴스를 받게 하는 단일 출처."""
    return _saver


async def close_checkpointer() -> None:
    """앱 종료(lifespan)에 풀 정리."""
    global _saver, _cm
    if _cm is not None:
        try:
            await _cm.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            log.warning("체크포인터 종료 중 오류(무시): %s", exc)
    _saver = None
    _cm = None
