"""블록 라우터 가족 공유 헬퍼 — blocks.py에서 분할(스펙 393 P1).

가족 모듈들이 공유하는 최소 헬퍼. 파사드(blocks.py)에 두면 가족→파사드 역방향 import 순환이
생기므로 최하위 모듈로 내린다(392 chat_graph_build와 같은 결). 파사드가 재수출한다.
"""

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _norm_description(data: dict) -> dict:
    """설명 정규화 — 공백뿐이면 None(스펙 148, 210)."""
    if "description" in data:
        data["description"] = (data["description"] or "").strip() or None
    return data


async def _commit_or_409(session: AsyncSession, detail: str) -> None:
    """이름 유니크 충돌을 500 대신 409로(스펙 148 — name unique 테이블 공용)."""
    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail) from err
