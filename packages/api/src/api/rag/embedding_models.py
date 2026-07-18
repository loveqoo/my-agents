"""임베딩 모델 해석·차원 가드 + 공용 컬렉션 로더 — shared.py에서 분할(스펙 398 P4).

차원 트랩 대응 — DB↔임베딩 모델 차이 3중 가드(스펙 020 함정3, no silent death):
  1) 생성: 임베딩 모델 probe → 실측 dims가 저장소 차원(RAG_EMBED_DIMS)과 다르면 409.
  2) 인제스트: 임베딩 벡터 길이 != Collection.dims면 status=error(메시지 보존), insert 0.
  3) 점검: GET /{id}/health — DB 컬럼/Collection 박제/모델 probe 3자 비교, drift 노출.
_load_collection은 다가족 공용 로더(collections·documents·search·reindex 전부 소비)라 동거.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import crypto
from ..model_registry import _probe
from ..models import RAG_EMBED_DIMS, Collection, ModelConfig


def _dim_mismatch(probed: int | None, target: int) -> str | None:
    """probe 실측 차원이 저장소 차원과 불일치하면 사유 문자열, 아니면 None(미상도 통과).

    probe 실패(None)는 막지 않는다 — 임베딩 서버가 잠시 죽어도 컬렉션 생성은 되게 하고,
    실제 불일치는 인제스트 시점(가드2)·health(가드3)에서 잡는다.
    """
    if probed is not None and probed != target:
        return (
            f"임베딩 모델의 출력 차원({probed})이 RAG 저장소 차원({target})과 다릅니다. "
            f"저장소(rag_chunks)는 vector({target})로 고정돼 있어 적재할 수 없습니다. "
            f"{target}차원 임베딩 모델을 선택하거나, 관리자에게 저장소 차원 정책 변경을 요청하세요."
        )
    return None


async def _load_collection(session: AsyncSession, cid: uuid.UUID) -> Collection | None:
    return (
        await session.execute(
            select(Collection)
            .where(Collection.id == cid)
            .options(selectinload(Collection.embedding_model).selectinload(ModelConfig.provider))
        )
    ).scalar_one_or_none()


async def _embedding_model(session: AsyncSession, model_id: uuid.UUID) -> ModelConfig | None:
    return (
        await session.execute(
            select(ModelConfig)
            .where(ModelConfig.id == model_id)
            .options(selectinload(ModelConfig.provider))
        )
    ).scalar_one_or_none()


async def _validate_embedding_model(session: AsyncSession, model_id: uuid.UUID) -> ModelConfig:
    """임베딩 모델 해석+검증(스펙 375·캠페인 374 T1-2) — 컬렉션 생성·재인덱싱 모델 선택 공유 단일 출처.

    이전엔 create_collection과 _resolve_reindex_model이 kind 강제·probe·차원 검사를 각각 복제해
    한쪽 규칙이 바뀌면 드리프트(codex 리뷰 P1). 규칙: 존재(400)·kind=embedding(400)·provider가
    있으면 probe 실측 차원이 저장소 고정 차원과 일치(불일치 409). provider 부재(레거시)는 probe
    생략 — _dim_mismatch가 '미상 통과' 규칙을 이미 가짐. 반환=검증된 모델.

    주의: 검색 시점 완전성 가드(search_collection의 em.kind 검사, 072 P2)는 실패 모드·메시지가 달라
    여기 합치지 않는다."""
    m = await _embedding_model(session, model_id)
    if m is None:
        raise HTTPException(status_code=400, detail="임베딩 모델을 찾을 수 없습니다.")
    if m.kind != "embedding":
        raise HTTPException(status_code=400, detail="임베딩(kind=embedding) 모델만 쓸 수 있습니다.")
    if m.provider is not None:  # 같은 차원(RAG_EMBED_DIMS)만 — probe 실측
        probe = await _probe(
            m.provider.base_url, crypto.decrypt(m.provider.api_key), m.model_id, "embedding"
        )
        msg = _dim_mismatch(probe.dims, RAG_EMBED_DIMS)
        if msg:
            raise HTTPException(status_code=409, detail=msg)
    return m
