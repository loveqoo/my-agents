"""모델 레지스트리 라우터 (008). LLM/임베딩 설정 CRUD.

api_key는 출력 시 마스킹되며, 수정 시 마스킹된 값을 그대로 보내면 기존 키를 보존한다.
지배 스펙: docs/spec/008-model-registry.md
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import ModelConfig
from . import crypto
from .schemas import ModelIn, ModelOut
from .serializers import model_to_out

router = APIRouter(prefix="/models", tags=["models"])


async def _clear_other_defaults(
    session: AsyncSession, kind: str, exclude_id: uuid.UUID | None = None
) -> None:
    """kind별 기본값은 하나만 — 나머지 is_default를 끈다(codex P2)."""
    rows = (
        await session.execute(
            select(ModelConfig).where(ModelConfig.kind == kind, ModelConfig.is_default.is_(True))
        )
    ).scalars().all()
    for r in rows:
        if exclude_id is None or r.id != exclude_id:
            r.is_default = False


@router.get("", response_model=list[ModelOut])
async def list_models(
    kind: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[ModelOut]:
    stmt = select(ModelConfig).order_by(ModelConfig.kind, ModelConfig.name)
    if kind:
        stmt = stmt.where(ModelConfig.kind == kind)
    rows = (await session.execute(stmt)).scalars().all()
    return [model_to_out(m) for m in rows]


@router.post("", response_model=ModelOut, status_code=201)
async def create_model(body: ModelIn, session: AsyncSession = Depends(get_session)) -> ModelOut:
    if body.is_default:
        await _clear_other_defaults(session, body.kind)
    m = ModelConfig(
        name=body.name, provider=body.provider, base_url=body.base_url,
        api_key=crypto.encrypt(body.api_key), model_id=body.model_id, kind=body.kind,
        is_default=body.is_default, params=body.params,
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)
    return model_to_out(m)


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(model_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ModelOut:
    m = await session.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="not found")
    return model_to_out(m)


@router.put("/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: uuid.UUID, body: ModelIn, session: AsyncSession = Depends(get_session)
) -> ModelOut:
    m = await session.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="not found")
    m.name = body.name
    m.provider = body.provider
    m.base_url = body.base_url
    m.model_id = body.model_id
    m.kind = body.kind
    if body.is_default:
        await _clear_other_defaults(session, body.kind, exclude_id=m.id)
    m.is_default = body.is_default
    m.params = body.params
    # 키 의미 구분: None/마스킹표시 = 보존, 빈 문자열 = 명시적 제거, 그 외 = 새 평문 암호화.
    if body.api_key is None or crypto.is_masked(body.api_key):
        pass  # 기존 암호화 키 보존
    elif body.api_key == "":
        m.api_key = None  # 명시적 제거
    else:
        m.api_key = crypto.encrypt(body.api_key)
    await session.commit()
    await session.refresh(m)
    return model_to_out(m)


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    m = await session.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(m)
    await session.commit()
