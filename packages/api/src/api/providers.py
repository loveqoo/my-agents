"""Provider 레지스트리 라우터 (035). LLM 연결처(엔드포인트+자격증명) CRUD.

provider 1회 등록 → 하위 모델이 base_url/api_key를 상속. api_key는 010 규약대로
암호화 저장·마스킹 출력하며, 수정 시 마스킹 값을 그대로 보내면 기존 키를 보존한다.
삭제는 매달린 모델이 있으면 차단(RESTRICT) → 409.

지배 스펙: docs/spec/archive/035-provider-entity.md
"""

import asyncio
import json
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog, crypto
from .db import get_session
from .model_registry import _probe
from .models import ModelConfig, Provider
from .schemas import (
    AvailableModel,
    AvailableModelsOut,
    ModelProbeResult,
    ProviderIn,
    ProviderOut,
    ProviderProbeIn,
)
from .serializers import provider_to_out

# GET /models 응답 raw 바이트 상한(learning 028·041 — 캡은 원천 바이트에서). 악성·오작동 서버
# 메모리 소진 차단. 2MB면 수천 모델 목록도 충분.
_MAX_MODELS_BYTES = 2 * 1024 * 1024

# GET /models 스트림 전체 벽시계 deadline(초). httpx timeout=10은 per-read 한도라
# slow-trickle(바이트당 <10s) 응답을 못 막는다 — 적대 리뷰 047. 상한 도달까지
# 누적해도 이 deadline 안에서 끝나야 코루틴을 오래 붙잡지 않는다.
_STREAM_DEADLINE = 20

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
        api_key=crypto.encrypt(body.api_key), kind=body.kind, description=body.description,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return provider_to_out(p, 0)


async def _list_remote_models(
    base_url: str, api_key: str | None
) -> tuple[bool, str, list[str]]:
    """프로바이더 base_url의 GET /models로 실모델 id 목록을 가져온다(통합 뷰 토글용).

    SSRF: base_url은 관리자 입력(신뢰경계 이미 넘음, _probe와 동일 판단 — learning 028). 단
    http(s) 스킴·타임아웃·raw 바이트 상한·data[*].id 타입 검증은 기본값으로 켠다.
    httpx timeout=10은 per-read(읽기 1회) 한도라, 1바이트씩 9초마다 흘리는 악성 응답이
    연결을 무한정 붙잡을 수 있다(적대 리뷰 047) → asyncio.timeout으로 스트림 전체에
    벽시계 deadline(_STREAM_DEADLINE)을 따로 건다. 둘 다 있어야 "타임아웃" 주장이 참이 된다.
    반환: (reachable, detail, ids). 비밀은 detail에 미포함.
    """
    if not base_url:
        return False, "base_url 없음", []
    if not base_url.lower().startswith(("http://", "https://")):
        return False, "http(s) 스킴만 허용", []
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.rstrip("/") + "/models"
    buf = bytearray()
    try:
        async with asyncio.timeout(_STREAM_DEADLINE):
            async with httpx.AsyncClient(timeout=10) as client:
                async with client.stream("GET", url, headers=headers) as r:
                    if r.status_code != 200:
                        return True, f"HTTP {r.status_code}", []  # 본문은 키 에코 가능 — 미노출
                    async for chunk in r.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > _MAX_MODELS_BYTES:
                            return True, "응답이 상한을 초과했습니다", []
    except (Exception, asyncio.TimeoutError):  # noqa: BLE001 — 네트워크 오류·deadline(상세 미노출)
        return False, "연결 실패", []
    try:
        data = json.loads(buf).get("data") or []
        ids = [str(m["id"]) for m in data if isinstance(m, dict) and m.get("id")]
    except Exception:  # noqa: BLE001
        return True, "응답 파싱 실패", []
    return True, "연결됨", ids


@router.get("/{provider_id}/available-models", response_model=AvailableModelsOut)
async def available_models(
    provider_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AvailableModelsOut:
    """프로바이더의 실모델을 나열하고 등록 여부·카탈로그 메타를 매겨 돌려준다(스펙 047 #8).

    이미 등록된 모델 중 원격 목록에 없는 것도 포함(토글 OFF가 가능하도록).
    """
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    reachable, detail, ids = await _list_remote_models(p.base_url, crypto.decrypt(p.api_key))

    rows = (
        await session.execute(
            select(ModelConfig).where(ModelConfig.provider_id == provider_id)
        )
    ).scalars().all()
    by_mid: dict[str, ModelConfig] = {m.model_id: m for m in rows}

    out: list[AvailableModel] = []
    seen: set[str] = set()
    for mid in ids:
        if mid in seen:
            continue
        seen.add(mid)
        m = by_mid.get(mid)
        out.append(
            AvailableModel(
                model_id=mid,
                registered=m is not None,
                registered_name=m.name if m else None,
                registered_id=m.id if m else None,
                catalog=catalog.lookup(mid),
            )
        )
    # 원격 목록에 없지만 등록돼 있는 모델 — 토글 OFF 노출용.
    for mid, m in by_mid.items():
        if mid not in seen:
            out.append(
                AvailableModel(
                    model_id=mid, registered=True, registered_name=m.name,
                    registered_id=m.id, catalog=catalog.lookup(mid),
                )
            )
    return AvailableModelsOut(reachable=reachable, detail=detail, models=out)


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
    p.kind = body.kind
    p.description = body.description
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
