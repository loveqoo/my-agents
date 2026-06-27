"""Provider 레지스트리 라우터 (035). LLM 연결처(엔드포인트+자격증명) CRUD.

provider 1회 등록 → 하위 모델이 base_url/api_key를 상속. api_key는 010 규약대로
암호화 저장·마스킹 출력하며, 수정 시 마스킹 값을 그대로 보내면 기존 키를 보존한다.
삭제는 매달린 모델이 있으면 차단(RESTRICT) → 409.

지배 스펙: docs/spec/archive/035-provider-entity.md
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto
from .db import get_session
from .model_registry import _probe
from .models import ModelConfig, Provider
from .schemas import ModelProbeResult, ProviderIn, ProviderOut, ProviderProbeIn
from .serializers import provider_to_out

router = APIRouter(prefix="/providers", tags=["providers"])


async def _model_counts(session: AsyncSession) -> dict[uuid.UUID, int]:
    """provider별 매달린 모델 수(목록 표시·삭제 안내용)."""
    rows = (
        await session.execute(
            select(ModelConfig.provider_id, func.count()).group_by(ModelConfig.provider_id)
        )
    ).all()
    return {pid: n for pid, n in rows}


@router.get("", response_model=list[ProviderOut])
async def list_providers(session: AsyncSession = Depends(get_session)) -> list[ProviderOut]:
    rows = (await session.execute(select(Provider).order_by(Provider.name))).scalars().all()
    counts = await _model_counts(session)
    return [provider_to_out(p, counts.get(p.id, 0)) for p in rows]


@router.post("/test", response_model=ModelProbeResult)
async def test_provider_config(body: ProviderProbeIn) -> ModelProbeResult:
    """저장 전 provider 폼으로 도달성 테스트(GET {base_url}/models). 마스킹 키면 무인증 시도."""
    api_key = None if (body.api_key and crypto.is_masked(body.api_key)) else body.api_key
    return await _probe(body.base_url, api_key, "", "chat")


@router.post("/{provider_id}/test", response_model=ModelProbeResult)
async def test_saved_provider(
    provider_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ModelProbeResult:
    """저장된 provider로 도달성 테스트(키 복호화)."""
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    return await _probe(p.base_url, crypto.decrypt(p.api_key), "", "chat")


@router.post("", response_model=ProviderOut, status_code=201)
async def create_provider(body: ProviderIn, session: AsyncSession = Depends(get_session)) -> ProviderOut:
    p = Provider(
        name=body.name, protocol=body.protocol, base_url=body.base_url,
        api_key=crypto.encrypt(body.api_key),
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return provider_to_out(p, 0)


@router.get("/{provider_id}", response_model=ProviderOut)
async def get_provider(
    provider_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ProviderOut:
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    counts = await _model_counts(session)
    return provider_to_out(p, counts.get(p.id, 0))


@router.put("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: uuid.UUID, body: ProviderIn, session: AsyncSession = Depends(get_session)
) -> ProviderOut:
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    p.name = body.name
    p.protocol = body.protocol
    p.base_url = body.base_url
    # 키 의미 구분: None/마스킹표시 = 보존, 빈 문자열 = 명시적 제거, 그 외 = 새 평문 암호화.
    if body.api_key is None or crypto.is_masked(body.api_key):
        pass  # 기존 암호화 키 보존
    elif body.api_key == "":
        p.api_key = None  # 명시적 제거
    else:
        p.api_key = crypto.encrypt(body.api_key)
    await session.commit()
    await session.refresh(p)
    counts = await _model_counts(session)
    return provider_to_out(p, counts.get(p.id, 0))


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    # 매달린 모델이 있으면 차단(RESTRICT). DB IntegrityError에 의존하지 않고 선제 검사로
    # 친절한 메시지를 준다(스펙 035 결정 2).
    n = (
        await session.execute(
            select(func.count()).select_from(ModelConfig).where(ModelConfig.provider_id == provider_id)
        )
    ).scalar_one()
    if n:
        raise HTTPException(
            status_code=409,
            detail=f"이 provider에 매달린 모델 {n}개가 있습니다 — 먼저 모델을 제거하세요.",
        )
    await session.delete(p)
    await session.commit()
