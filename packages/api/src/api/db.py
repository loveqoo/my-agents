"""비동기 SQLAlchemy 엔진/세션 + 스키마 마이그레이션."""

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


async def get_or_404[T](
    session: AsyncSession, model: type[T], ident: object, detail: str = "not found"
) -> T:
    """PK 조회 후 없으면 404(정본, 스펙 297). **순수 존재 체크만** — 소유권/가시성 게이트는 호출부가
    별도로 수행한다(이 헬퍼는 SELECT-WHERE 스코프를 대체하지 않는다). session.get은 항상 PK 조회라
    스코프 우회 위험이 없다."""
    obj = await session.get(model, ident)
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    return obj


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

    init_db 맨 앞에 둬 운영자가 raw asyncpg 트레이스 대신 조치를 보게 하고, "연결 실패"와
    "마이그레이션 실패"(스펙 330 fail-fast)를 다른 메시지로 구분한다(여기 통과 = DB 도달 가능).
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
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


async def init_db() -> None:
    """시작 시 DB 프리플라이트 → alembic upgrade head(**fail-fast, 스펙 330**) + 비어있으면 시드.

    구 create_all 폴백은 제거됐다 — alembic 실패를 warning+대체 스키마+head 스탬프로 조용히
    우회해, 고장난 마이그레이션이 성공처럼 보이고 스키마 드리프트가 버전 기록과 어긋난 채
    침묵했다(스펙 329 codex P1 실증). alembic이 스키마의 단일 진실이다: virgin DB도 전 체인으로
    빌드되고(pgvector 확장은 b2c3d4e5f6a7가 보장), 실패는 가리지 않고 부팅을 중단한다."""
    await _preflight()  # DB 도달성 먼저 — 실패 시 명확 종료
    try:
        await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    except Exception as e:
        logger.error(
            "alembic upgrade head 실패 — 부팅을 중단합니다(스펙 330: 폴백 없음).\n"
            "  흔한 원인:\n"
            "  · 새 마이그레이션 파일 결함(최근 리비전을 검토하세요)\n"
            "  · DB의 alembic_version이 이 코드가 모르는 리비전(구 코드로 신 DB 부팅 — 코드를\n"
            "    최신으로 올리거나 DATABASE_URL이 맞는 DB인지 확인)\n"
            "  · pgvector 확장 생성 권한 부재(관리형 PG·비수퍼유저 — 번들 postgres 이미지를 쓰거나\n"
            "    수퍼유저로 `CREATE EXTENSION vector` 1회 실행 후 재기동)\n"
            "  · 스키마 수동 변경 드리프트(마이그레이션이 기대하는 상태와 불일치)\n"
            "  진단: packages/api에서 `uv run alembic current` / `uv run alembic history | head`",
            exc_info=True,
        )
        raise RuntimeError(
            "DB 마이그레이션 실패 — 스키마를 조용히 대체하지 않습니다(스펙 330). "
            "로그의 원인·진단 안내를 확인 후 재기동하세요."
        ) from e

    from .seed import seed_if_empty

    async with SessionLocal() as session:
        await seed_if_empty(session)
        await _recover_stale_reindex(session)


async def _recover_stale_reindex(session: AsyncSession) -> None:
    """부팅 시 stale 재인덱싱 잠금 회수(스펙 312) — 프로세스가 재인덱싱 중 죽으면 status가
    'reindexing'에 갇힌다. 재인덱싱 스왑은 원자적이라 데이터는 항상 일관 상태(구 또는 신)이므로
    'ready'로 되돌려도 안전하다(반쪽 없음). 갇힌 채 두면 그 컬렉션이 영영 접근 불가(no silent stuck).

    **경계(codex F2)**: 단일 워커 배포(uvicorn --reload=워커 1) 가정. 멀티워커면 워커 B의 부팅이
    워커 A의 *살아있는* 재인덱싱 잠금을 풀 수 있다(전역 status만 보고 회수). 진짜 멀티워커가 필요하면
    started_at/heartbeat 리스로 "오래된 것만" 회수해야 한다(스펙 312 OUT — 이 개인 도구는 단일 워커)."""
    from sqlalchemy import update as _update

    from .models import Collection

    res = await session.execute(
        _update(Collection).where(Collection.status == "reindexing").values(status="ready")
    )
    await session.commit()
    if res.rowcount:
        logger.warning("stale 재인덱싱 잠금 %d건 회수(status reindexing→ready)", res.rowcount)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
