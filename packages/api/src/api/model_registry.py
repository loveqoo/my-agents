"""모델 레지스트리 라우터 (008). LLM/임베딩 설정 CRUD.

api_key는 출력 시 마스킹되며, 수정 시 마스킹된 값을 그대로 보내면 기존 키를 보존한다.
지배 스펙: docs/spec/008-model-registry.md
"""

import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto
from .db import get_session
from .models import ModelConfig, Provider
from .schemas import ModelIn, ModelOut, ModelProbeIn, ModelProbeResult
from .serializers import model_to_out

router = APIRouter(prefix="/models", tags=["models"])


async def _probe(
    base_url: str, api_key: str | None, model_id: str, kind: str = "chat"
) -> ModelProbeResult:
    """kind별 연결 테스트. 비밀은 결과에 미포함.

    - chat:      `{base_url}/models` 목록에 model_id가 있는지(가용성) 확인.
    - embedding: `{base_url}/embeddings`를 샘플 입력으로 호출해 벡터가 돌아오는지(기능) 확인.
    """
    if not base_url:
        return ModelProbeResult(
            ok=False, reachable=False, modelAvailable=False, latencyMs=0, detail="base_url 없음"
        )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    base = base_url.rstrip("/")
    t0 = time.perf_counter()
    if kind == "embedding":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    base + "/embeddings",
                    headers=headers,
                    json={"model": model_id, "input": "ping"},
                )
        except Exception:  # noqa: BLE001 — 네트워크 오류(상세 미노출)
            ms = int((time.perf_counter() - t0) * 1000)
            return ModelProbeResult(
                ok=False, reachable=False, modelAvailable=False, latencyMs=ms, detail="연결 실패"
            )
        ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return ModelProbeResult(
                ok=False, reachable=True, modelAvailable=False, latencyMs=ms, detail=f"HTTP {r.status_code}"
            )
        try:
            vec = ((r.json().get("data") or [{}])[0]).get("embedding") or []
        except Exception:  # noqa: BLE001
            vec = []
        if vec:
            return ModelProbeResult(
                ok=True, reachable=True, modelAvailable=True, latencyMs=ms,
                detail=f"임베딩 OK · {len(vec)}차원", dims=len(vec),
            )
        return ModelProbeResult(
            ok=True, reachable=True, modelAvailable=False, latencyMs=ms, detail="연결됨 · 임베딩 응답 없음"
        )

    # kind == "chat" (기본)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(base + "/models", headers=headers)
    except Exception:  # noqa: BLE001 — 네트워크 오류(상세는 노출 안 함)
        ms = int((time.perf_counter() - t0) * 1000)
        return ModelProbeResult(
            ok=False, reachable=False, modelAvailable=False, latencyMs=ms, detail="연결 실패"
        )
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        # 본문은 키를 에코할 수 있어 노출 안 함 — 상태코드만.
        return ModelProbeResult(
            ok=False, reachable=True, modelAvailable=False, latencyMs=ms, detail=f"HTTP {r.status_code}"
        )
    try:
        ids = [m.get("id") for m in (r.json().get("data") or [])]
    except Exception:  # noqa: BLE001
        ids = []
    available = model_id in ids if model_id else False
    detail = "연결됨" + (" · 모델 사용 가능" if available else " · 모델 미발견")
    return ModelProbeResult(ok=True, reachable=True, modelAvailable=available, latencyMs=ms, detail=detail)


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


async def _get_with_provider(session: AsyncSession, model_id: uuid.UUID) -> ModelConfig | None:
    """모델 1건을 provider 관계와 함께 로드(직렬화·테스트에 provider 필요)."""
    return (
        await session.execute(
            select(ModelConfig)
            .where(ModelConfig.id == model_id)
            .options(selectinload(ModelConfig.provider))
        )
    ).scalar_one_or_none()


@router.get("", response_model=list[ModelOut])
async def list_models(
    kind: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[ModelOut]:
    stmt = (
        select(ModelConfig)
        .options(selectinload(ModelConfig.provider))
        .order_by(ModelConfig.kind, ModelConfig.name)
    )
    if kind:
        stmt = stmt.where(ModelConfig.kind == kind)
    rows = (await session.execute(stmt)).scalars().all()
    return [model_to_out(m) for m in rows]


@router.post("/test", response_model=ModelProbeResult)
async def test_model_config(
    body: ModelProbeIn, session: AsyncSession = Depends(get_session)
) -> ModelProbeResult:
    """입력값(새 모델/편집)으로 연결 테스트. 연결처는 선택한 provider에서 취득."""
    p = await session.get(Provider, body.provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="provider not found")
    return await _probe(p.base_url, crypto.decrypt(p.api_key), body.model_id, body.kind)


@router.post("/{model_id}/test", response_model=ModelProbeResult)
async def test_saved_model(
    model_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ModelProbeResult:
    """저장된 모델로 연결 테스트(provider 자격증명 복호화)."""
    m = await _get_with_provider(session, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="not found")
    return await _probe(m.provider.base_url, crypto.decrypt(m.provider.api_key), m.model_id, m.kind)


async def _require_provider(session: AsyncSession, provider_id: uuid.UUID) -> None:
    if await session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=400, detail="provider not found — provider를 먼저 등록하세요.")


@router.post("", response_model=ModelOut, status_code=201)
async def create_model(body: ModelIn, session: AsyncSession = Depends(get_session)) -> ModelOut:
    await _require_provider(session, body.provider_id)
    if body.is_default:
        await _clear_other_defaults(session, body.kind)
    m = ModelConfig(
        name=body.name, provider_id=body.provider_id, model_id=body.model_id,
        kind=body.kind, is_default=body.is_default, params=body.params,
    )
    session.add(m)
    await session.commit()
    return model_to_out(await _get_with_provider(session, m.id))


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(model_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ModelOut:
    m = await _get_with_provider(session, model_id)
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
    await _require_provider(session, body.provider_id)
    m.name = body.name
    m.provider_id = body.provider_id
    m.model_id = body.model_id
    m.kind = body.kind
    if body.is_default:
        await _clear_other_defaults(session, body.kind, exclude_id=m.id)
    m.is_default = body.is_default
    m.params = body.params
    await session.commit()
    return model_to_out(await _get_with_provider(session, m.id))


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    m = await session.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(m)
    await session.commit()
