"""비동기 SQLAlchemy 엔진/세션 + 스키마 마이그레이션."""

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"
)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


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
    """시작 시 alembic upgrade head (실패 시 create_all 폴백) + 비어있으면 시드."""
    try:
        await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    except Exception:  # noqa: BLE001 — 부팅은 항상 성공해야 한다
        logger.warning(
            "alembic upgrade head 실패 — create_all로 폴백합니다.", exc_info=True
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
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
