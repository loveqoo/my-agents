"""비동기 SQLAlchemy 엔진/세션 + 스키마 생성."""

import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"
)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    """시작 시 스키마 생성 (마이그레이션은 추후) + 비어있으면 시드."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from .seed import seed_if_empty

    async with SessionLocal() as session:
        await seed_if_empty(session)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
