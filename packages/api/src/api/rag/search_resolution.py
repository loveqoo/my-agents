"""검색 가능 컬렉션 해석 — shared.py에서 분할(스펙 398 P3, 순수 이동).

시험 엔드포인트·평가 러너(eval_runs) 공용(스펙 140에서 추출) — api.rag 재수출 표면 유지.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from .embedding_models import _load_collection


async def resolve_search_collection(session: AsyncSession, cid: uuid.UUID) -> dict:
    """검색 가능한 컬렉션 해석(시험 엔드포인트·평가 러너 공용 — 스펙 140에서 추출, 시맨틱 불변).
    완전성/kind 가드 포함, 실패는 HTTPException(404/400). api_key는 백엔드 전용 복호화."""
    c = await _load_collection(session, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    em = c.embedding_model
    ep = em.provider if em else None
    if em is None or ep is None or not ep.base_url or not em.model_id:
        raise HTTPException(
            status_code=400,
            detail="이 컬렉션은 임베딩 모델/provider 설정이 불완전해 검색할 수 없습니다.",
        )
    # kind 가드(적대 리뷰 072 P2): 모델 수정으로 컬렉션 참조 모델이 chat 등으로 바뀌면, 완전성만
    # 보면 통과해 임베딩 시도 → provider 502로 뭉개진다. embedding 모델이 아니면 설정 오류 400으로 명확히.
    if em.kind != "embedding":
        raise HTTPException(
            status_code=400,
            detail=f"컬렉션의 모델이 임베딩(kind=embedding)이 아닙니다(현재 kind={em.kind}). 검색할 수 없습니다.",
        )
    return {
        "id": c.id,
        "name": c.name,
        "embed_base_url": ep.base_url,
        "embed_api_key": crypto.decrypt(ep.api_key),  # 백엔드 전용 — 응답 미노출
        "embed_model_id": em.model_id,
    }
