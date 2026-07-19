"""모델 레지스트리 라우터 (008). LLM/임베딩 설정 CRUD.

api_key는 출력 시 마스킹되며, 수정 시 마스킹된 값을 그대로 보내면 기존 키를 보존한다.
지배 스펙: docs/spec/008-model-registry.md
"""

import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto
from .auth import current_principal
from .block_versions import delete_block_history, record_block_version
from .db import get_or_404, get_session
from .models import Agent, AgentVersion, Collection, ModelConfig, Provider, User
from .ownership import is_privileged
from .schemas import ModelIn, ModelOut, ModelProbeIn, ModelProbeResult
from .serializers import model_to_out

router = APIRouter(prefix="/models", tags=["models"])


async def require_model_manage(
    principal: User | str = Depends(current_principal),
) -> User | str:
    """모델/프로바이더 변이 게이트(스펙 150, codex High) — 기본 모델·연결처는 채팅·메모리·평가의
    전역 동작과 비용면을 바꾸므로 특권(머신 토큰·superuser·admin)만. member는 403.
    (읽기·연결 테스트는 인증만 — 기존과 동일.)"""
    if not is_privileged(principal):
        raise HTTPException(status_code=403, detail="모델 관리 권한이 없습니다")
    return principal


_manage = Depends(require_model_manage)


async def _commit_or_409(session: AsyncSession, detail: str) -> None:
    """유니크 충돌(kind당 기본 1개 부분 인덱스·이름)을 500 대신 409로(스펙 150 — 동시 지정 레이스)."""
    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail) from err


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
        except Exception:
            ms = int((time.perf_counter() - t0) * 1000)
            return ModelProbeResult(
                ok=False, reachable=False, modelAvailable=False, latencyMs=ms, detail="연결 실패"
            )
        ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return ModelProbeResult(
                ok=False,
                reachable=True,
                modelAvailable=False,
                latencyMs=ms,
                detail=f"HTTP {r.status_code}",
            )
        try:
            vec = ((r.json().get("data") or [{}])[0]).get("embedding") or []
        except Exception:
            vec = []
        if vec:
            return ModelProbeResult(
                ok=True,
                reachable=True,
                modelAvailable=True,
                latencyMs=ms,
                detail=f"임베딩 OK · {len(vec)}차원",
                dims=len(vec),
            )
        return ModelProbeResult(
            ok=True,
            reachable=True,
            modelAvailable=False,
            latencyMs=ms,
            detail="연결됨 · 임베딩 응답 없음",
        )

    # kind == "chat" (기본)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(base + "/models", headers=headers)
    except Exception:
        ms = int((time.perf_counter() - t0) * 1000)
        return ModelProbeResult(
            ok=False, reachable=False, modelAvailable=False, latencyMs=ms, detail="연결 실패"
        )
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        # 본문은 키를 에코할 수 있어 노출 안 함 — 상태코드만.
        return ModelProbeResult(
            ok=False,
            reachable=True,
            modelAvailable=False,
            latencyMs=ms,
            detail=f"HTTP {r.status_code}",
        )
    try:
        ids = [m.get("id") for m in (r.json().get("data") or [])]
    except Exception:
        ids = []
    if not model_id:
        # 프로바이더 레벨 테스트(특정 모델 미지정, 스펙 164) — 목록 존재 여부로 판정한다.
        # 빈 model_id를 "미발견"으로 오판하던 버그: 프로바이더는 잘 붙었고 모델도 있는데
        # "연결됨 · 모델 미발견"이 떠 사용자가 오해했다(등록 화면엔 모델이 주르륵). 개수로 정직하게.
        n = len(ids)
        return ModelProbeResult(
            ok=True,
            reachable=True,
            modelAvailable=n > 0,
            latencyMs=ms,
            detail=f"연결됨 · 모델 {n}개 발견" if n else "연결됨 · 모델 목록 비어있음",
        )
    available = model_id in ids
    detail = "연결됨" + (" · 모델 사용 가능" if available else " · 모델 미발견")
    return ModelProbeResult(
        ok=True, reachable=True, modelAvailable=available, latencyMs=ms, detail=detail
    )


async def _clear_other_defaults(
    session: AsyncSession, kind: str, exclude_id: uuid.UUID | None = None
) -> None:
    """kind별 기본값은 하나만 — 나머지 is_default를 끈다(codex P2).

    해제를 **즉시 flush** — 부분 유니크 인덱스(uq_models_default_per_kind, 스펙 150)는 문장 단위로
    검사되므로, 해제 UPDATE가 새 기본 지정보다 먼저 실행됨을 보장해야 자기 트랜잭션과 안 충돌한다."""
    rows = (
        (
            await session.execute(
                select(ModelConfig).where(
                    ModelConfig.kind == kind, ModelConfig.is_default.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    changed = False
    for row in rows:
        if exclude_id is None or row.id != exclude_id:
            row.is_default = False
            changed = True
    if changed:
        await session.flush()


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
    p = await get_or_404(session, Provider, body.provider_id, detail="provider not found")
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
        raise HTTPException(
            status_code=400, detail="provider not found — provider를 먼저 등록하세요."
        )


@router.post("", response_model=ModelOut, status_code=201, dependencies=[_manage])
async def create_model(body: ModelIn, session: AsyncSession = Depends(get_session)) -> ModelOut:
    await _require_provider(session, body.provider_id)
    if body.is_default:
        await _clear_other_defaults(session, body.kind)
    m = ModelConfig(
        name=body.name,
        provider_id=body.provider_id,
        model_id=body.model_id,
        kind=body.kind,
        is_default=body.is_default,
        params=body.params,
        capabilities=body.capabilities,  # 능력 선언(스펙 408)
        meta=body.meta,
    )
    session.add(m)
    await _commit_or_409(session, "동시 변경 충돌 또는 중복 — 다시 시도하세요.")
    await session.refresh(m)
    await record_block_version(session, "model", m)  # v1 이력(스펙 369)
    await session.commit()
    reloaded = await _get_with_provider(session, m.id)
    assert reloaded is not None  # 방금 커밋한 행의 재로드 — 동시 삭제 레이스 외엔 불가
    return model_to_out(reloaded)


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(model_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ModelOut:
    m = await _get_with_provider(session, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="not found")
    return model_to_out(m)


@router.put("/{model_id}", response_model=ModelOut, dependencies=[_manage])
async def update_model(
    model_id: uuid.UUID, body: ModelIn, session: AsyncSession = Depends(get_session)
) -> ModelOut:
    m = await get_or_404(session, ModelConfig, model_id)
    await _require_provider(session, body.provider_id)
    m.name = body.name
    m.provider_id = body.provider_id
    m.model_id = body.model_id
    m.kind = body.kind
    if body.is_default:
        await _clear_other_defaults(session, body.kind, exclude_id=m.id)
    m.is_default = body.is_default
    m.params = body.params
    m.capabilities = body.capabilities  # 능력 선언(스펙 408)
    m.meta = body.meta
    # is_default·meta는 payload 제외(스펙 369 §2) — 운영-only 변경은 버전 무증가.
    await record_block_version(session, "model", m)
    await _commit_or_409(session, "동시 변경 충돌 또는 중복 — 다시 시도하세요.")
    reloaded = await _get_with_provider(session, m.id)
    assert reloaded is not None  # 방금 커밋한 행의 재로드 — 동시 삭제 레이스 외엔 불가
    return model_to_out(reloaded)


@router.put("/{model_id}/default", response_model=ModelOut, dependencies=[_manage])
async def set_default_model(
    model_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ModelOut:
    """이 모델을 그 kind(chat/embedding)의 기본으로 지정 — 같은 kind의 기존 기본은 자동 해제
    (스펙 150, 실사용 버그 #1: 등록 모달에만 기본 스위치가 있어 삭제 후 재등록으로만 전환 가능했다).
    전용 액션인 이유: 프론트가 부분 데이터로 full PUT을 재구성하면 params/meta 유실 위험."""
    m = await get_or_404(session, ModelConfig, model_id)
    if m.kind not in ("chat", "embedding"):
        # 레거시/수동 행 방어(codex 150) — 런타임은 chat/embedding 기본만 읽으므로 그 외 kind의
        # "기본 지정 성공"은 아무 효과 없는 거짓 성공이 된다.
        raise HTTPException(
            status_code=400,
            detail=f"kind={m.kind!r}는 기본 지정 대상이 아닙니다(chat/embedding만).",
        )
    await _clear_other_defaults(session, m.kind, exclude_id=m.id)
    m.is_default = True
    await _commit_or_409(
        session, "동시에 다른 기본 지정이 있었습니다 — 새로고침 후 다시 시도하세요."
    )
    reloaded = await _get_with_provider(session, m.id)
    assert reloaded is not None  # 방금 커밋한 행의 재로드 — 동시 삭제 레이스 외엔 불가
    return model_to_out(reloaded)


@router.delete("/{model_id}", status_code=204, dependencies=[_manage])
async def delete_model(model_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    m = await get_or_404(session, ModelConfig, model_id)
    # 에이전트는 모델을 *이름*으로 참조(FK 없음 — learning 042). 참조 중이면 삭제 차단해
    # 런타임이 사라진 모델을 가리키지 않게 한다. column(model)·config.model 둘 다 검사.
    refs = (
        await session.execute(
            select(func.count())
            .select_from(Agent)
            .where(or_(Agent.model == m.name, Agent.config["model"].astext == m.name))
        )
    ).scalar_one()
    if refs:
        raise HTTPException(
            status_code=409,
            detail=f"이 모델을 참조하는 에이전트 {refs}개가 있습니다 — 먼저 에이전트의 모델을 바꾸세요.",
        )
    # 아카이브된 버전 스냅샷도 검사(적대 리뷰 047): live 참조가 없어도 옛 버전 config가
    # 이 모델을 가리키면, 그 버전으로 롤백(agents.py: agent.model = cfg["model"]) 시
    # 사라진 모델을 가리킨다. live보다 약한 결합이라 별도 메시지로 구분.
    ver_refs = (
        await session.execute(
            select(func.count())
            .select_from(AgentVersion)
            .where(AgentVersion.config["model"].astext == m.name)
        )
    ).scalar_one()
    if ver_refs:
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 모델을 참조하는 에이전트 버전 스냅샷 {ver_refs}개가 있습니다 — "
                "롤백 시 사라진 모델을 가리키게 됩니다. 해당 버전을 정리하거나 모델명을 유지하세요."
            ),
        )
    # RAG 컬렉션은 embedding_model_id FK(RESTRICT)로 모델을 가리킨다(스펙 048). 참조 중이면
    # DB가 IntegrityError를 던져 500이 된다(적대 리뷰 048) — 먼저 명시적으로 검사해 409로 안내.
    col_refs = (
        await session.execute(
            select(func.count())
            .select_from(Collection)
            .where(Collection.embedding_model_id == m.id)
        )
    ).scalar_one()
    if col_refs:
        raise HTTPException(
            status_code=409,
            detail=f"이 임베딩 모델을 사용하는 RAG 컬렉션 {col_refs}개가 있습니다 — 먼저 해당 컬렉션을 삭제하세요.",
        )
    await delete_block_history(session, "model", m.id)  # 스펙 369
    await session.delete(m)
    await session.commit()
