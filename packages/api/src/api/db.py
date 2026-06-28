"""비동기 SQLAlchemy 엔진/세션 + 스키마 마이그레이션."""

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"
)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def _mask_dsn(dsn: str) -> str:
    """로그용 DSN — 비밀번호만 ***로 가린다(비밀값 비노출)."""
    # postgresql+asyncpg://user:PASSWORD@host:port/db → 가운데 :pw@ 구간만 마스킹.
    if "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    if "@" not in rest:
        return dsn
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{host}"


async def _preflight() -> None:
    """DB 연결 프리플라이트 — 도달 불가면 명확한 조치 메시지로 RuntimeError.

    이걸 init_db 맨 앞에 두면 (1) 운영자가 raw asyncpg 트레이스 대신 조치를 보고,
    (2) create_all 폴백의 `engine.begin()`이 *또* 연결예외로 이중 throw하던 문제가
    구조적으로 사라진다(여기까지 왔으면 DB는 도달 가능).
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 — 연결 계층 전반(asyncpg/SQLAlchemy)을 한 번에
        masked = _mask_dsn(DATABASE_URL)
        logger.error(
            "DB 연결 실패 — 부팅을 중단합니다.\n"
            "  DATABASE_URL = %s\n"
            "  · postgres 미기동? `docker compose up -d postgres` 후 재시도\n"
            "  · 호스트/포트/자격증명(.env)·방화벽 확인\n"
            "  원본 오류: %s",
            masked,
            e,
        )
        raise RuntimeError(
            f"DB 연결 실패: {masked} — postgres 기동 여부와 DATABASE_URL을 확인하세요."
        ) from e


def _alembic_config() -> Config:
    """packages/api/alembic.ini 기준으로 Alembic Config 구성."""
    # db.py = packages/api/src/api/db.py -> parents[2] = packages/api
    api_root = Path(__file__).resolve().parents[2]
    # 임베디드 실행 시 alembic env.py의 fileConfig가 uvicorn 로깅을 덮어쓰지 않도록.
    os.environ.setdefault("ALEMBIC_EMBEDDED", "1")
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "alembic"))
    return cfg


async def init_db():
    """시작 시 DB 프리플라이트 → alembic upgrade head (실패 시 create_all 폴백) + 비어있으면 시드."""
    await _preflight()  # DB 도달성 먼저 — 실패 시 명확 종료(폴백 이중 throw 제거)
    try:
        await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    except Exception:  # noqa: BLE001 — 부팅은 항상 성공해야 한다
        logger.warning(
            "alembic upgrade head 실패 — create_all로 폴백합니다.", exc_info=True
        )
        try:
            async with engine.begin() as conn:
                # 폴백도 pgvector 확장을 보장한다(마이그레이션 b2c3d4e5f6a7와 패리티). 없으면 바로 뒤
                # create_all이 rag_chunks의 Vector 컬럼을 만들다 실패한다. 확장은 이 플랫폼의 *하드
                # 요구*다(코어 모델이 Vector 컬럼을 선언, docker가 pgvector 이미지를 번들). 그래서
                # "RAG만 비활성, 나머지 동작"으로 **부분 부팅하지 않는다** — create_all은 all-or-nothing
                # 인데다(적대리뷰 058 P1), Vector 테이블만 빼고 만들면 head 스탬프와 엮여 "나중에
                # pgvector를 고쳐도 rag_chunks가 영영 안 생기는" 더 큰 함정이 된다. 만들 수 없으면
                # 가리지 말고 또렷한 조치 메시지로 fail-closed 한다.
                # (이미 설치된 pgvector면 IF NOT EXISTS가 비-수퍼유저에서도 no-op이라 관리형 PG도 통과.)
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.run_sync(Base.metadata.create_all)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "create_all 폴백 실패 — 스키마를 만들 수 없습니다.\n"
                "  · 대개 pgvector 확장 부재/권한 문제입니다(코어 모델이 Vector 컬럼을 씁니다).\n"
                "  · `docker compose up -d postgres`(pgvector 번들 이미지)를 쓰거나,\n"
                "    수퍼유저로 `CREATE EXTENSION vector`를 1회 실행 후 재기동하세요.",
                exc_info=True,
            )
            raise RuntimeError(
                "스키마 생성 실패 — pgvector 확장이 필요합니다(번들 postgres 이미지 사용 또는 "
                "수퍼유저로 CREATE EXTENSION vector 후 재기동)."
            ) from e
        # create_all로 만든 스키마는 현재 모델(=head)과 동일하므로 head로 스탬프해
        # alembic_version을 남긴다 → 이후 마이그레이션이 우회되지 않게.
        try:
            await asyncio.to_thread(command.stamp, _alembic_config(), "head")
        except Exception:  # noqa: BLE001
            logger.warning("alembic stamp head 실패", exc_info=True)

    from .seed import seed_if_empty

    async with SessionLocal() as session:
        await seed_if_empty(session)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
