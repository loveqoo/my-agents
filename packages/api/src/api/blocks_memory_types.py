"""메모리 타입 라우트(시스템 정의 봉인) — blocks.py에서 분할(스펙 393 P2, 순수 이동).

생성·삭제·개명은 403 봉인(스펙 387 후속) — 죽은 옵션('단기(세션)') 재발 방지. 설명 수정만 허용.
assert_memory_names_exist는 에이전트 저장 검증(agents/crud_routes 소비). 파사드는 blocks.py.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .block_versions import record_block_version
from .blocks_shared import _commit_or_409
from .db import get_or_404, get_session
from .models import MemoryType
from .references import config_names
from .schemas import MemoryTypeIn, MemoryTypeOut

router = APIRouter(tags=["blocks"])


@router.get("/memory-types", response_model=list[MemoryTypeOut])
async def list_memory_types(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(MemoryType))
    return result.scalars().all()


@router.post("/memory-types", response_model=MemoryTypeOut, status_code=201)
async def create_memory_type(
    body: MemoryTypeIn,  # noqa: ARG001 — API 형태 보존(요청 스키마 검증은 유지, 본문은 미사용)
) -> Any:
    # 시스템 정의 봉인(스펙 387 후속, 구남님 결정) — 실동작 기억 기능은 '장기 기억 (mem0)' 하나뿐이라
    # 새 블록은 "골라도 무동작"인 죽은 옵션이 된다(단기(세션) 재발 방지). UI는 이미 읽기 전용(스펙 016)
    # 이었고, 이 백엔드 라우트가 남은 구멍이었다. 새 기억 메커니즘이 생기면 그 스펙이 이 봉인을 푼다.
    raise HTTPException(
        status_code=403,
        detail="기억 블록은 시스템 정의라 생성할 수 없습니다 — 실동작 기억 기능은 '장기 기억 (mem0)' 하나입니다.",
    )


@router.get("/memory-types/{id}", response_model=MemoryTypeOut)
async def get_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    return await get_or_404(session, MemoryType, id)


@router.put("/memory-types/{id}", response_model=MemoryTypeOut)
async def update_memory_type(
    id: uuid.UUID, body: MemoryTypeIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await get_or_404(session, MemoryType, id)
    # 이름/키 봉인(스펙 387 후속) — 런타임(memory_enabled)·에이전트 config가 **이름 문자열**로 판정하므로
    # 개명하면 참조가 조용히 끊겨 기억이 꺼진다. 설명(scope·body) 수정만 허용(문구 정정 경로 보존).
    if body.name != obj.name or body.key != obj.key:
        raise HTTPException(
            status_code=403,
            detail="기억 블록의 이름·키는 시스템 정의라 바꿀 수 없습니다 — 설명(scope·body)만 수정할 수 있습니다.",
        )
    for key, value in body.model_dump().items():
        setattr(obj, key, value)
    await record_block_version(session, "memory-type", obj)  # 스펙 369 관문
    await _commit_or_409(session, "동시 편집과 겹쳤습니다 — 다시 시도하세요.")
    await session.refresh(obj)
    return obj


@router.delete("/memory-types/{id}", status_code=204)
async def delete_memory_type(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    # 시스템 정의 봉인(스펙 387 후속) — 생성이 막혀 있어 지우면 복구 불능(대칭). 참조 가드(387)는
    # 이 봉인이 대체한다(참조 여부와 무관하게 삭제 불가).
    await get_or_404(session, MemoryType, id)
    raise HTTPException(status_code=403, detail="기억 블록은 시스템 정의라 삭제할 수 없습니다.")


async def assert_memory_names_exist(session: AsyncSession, cfg: dict) -> None:
    """에이전트 저장 시 memories 이름 존재 검증(스펙 387) — assert_node_refs_exist(316)와 같은 규칙.

    에이전트 레벨 + 노드 레벨(스펙 268) memories의 각 이름이 등록된 기억 블록에 있어야 저장된다.
    없는 이름이 config에 남으면 런타임이 조용히 무시해 기억이 소리 없이 꺼진다("설정했는데 무동작"
    — 죽은 '단기(세션)' 옵션과 같은 부류). 저장 시점 422로 이른 실패."""
    names = set(config_names(cfg, "memories"))
    for node in cfg.get("nodes") or []:
        if isinstance(node, dict):
            names |= set(config_names(node, "memories"))
    if not names:
        return
    rows = set(
        (await session.execute(select(MemoryType.name).where(MemoryType.name.in_(names)))).scalars()
    )
    missing = sorted(names - rows)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"존재하지 않는 기억: {', '.join(missing[:5])} — 등록된 기억 블록만 선택할 수 있습니다.",
        )
