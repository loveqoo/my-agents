"""배치 잡 공유 헬퍼 — jobs.py에서 분할(스펙 395 P2).

전 잡이 공유하는 BatchConfig 접근. 파사드는 jobs.py(재수출 계약).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BatchConfig


async def _get_config(session: AsyncSession) -> BatchConfig:
    """싱글톤 BatchConfig 1행 확보(없으면 생성). 값은 기본 NULL."""
    cfg = (await session.execute(select(BatchConfig).limit(1))).scalars().first()
    if cfg is None:
        cfg = BatchConfig()
        session.add(cfg)
        await session.flush()
    return cfg
