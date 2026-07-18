"""RAG 컬렉션 해석 — chat_context.py에서 분할(스펙 394 P2, 순수 이동).

파사드는 chat_context.py(재수출 계약).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto
from .models import Collection, ModelConfig
from .references import config_names

log = logging.getLogger("api.chat")


def _rag_collection_entry(c: Collection) -> dict | None:
    """컬렉션 → 검색 배선 dict — embedding 모델/provider 불완전이면 None(검색 불가 skip)."""
    em = c.embedding_model
    ep = em.provider if em else None
    if em is None or ep is None or not ep.base_url or not em.model_id:
        return None
    return {
        "id": c.id,
        "name": c.name,
        "embed_base_url": ep.base_url,
        "embed_api_key": crypto.decrypt(ep.api_key),
        "embed_model_id": em.model_id,
    }


async def _resolve_rag(db: AsyncSession, cfg: dict, remote: bool) -> tuple[list[dict], list[str]]:
    """RAG 컬렉션 해석(스펙 037) — vectorTables(이름 목록) → 검색 도구 배선용 dict.

    질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델**로 임베딩해야 같은 벡터 공간(035 진실원).
    provider 불완전 컬렉션은 검색 불가라 skip(graceful). 컬렉션은 전부 공용(스펙 172) — 가시성 축
    제거, 관리(수정·삭제)는 소유자만. 원격(code/external)은 비로컬이라 빈 결과.
    반환 (rag_collections, unresolved — 해석 실패 이름은 트레이스로 표면화, 타자검증 F)."""
    vt_names = config_names(cfg, "vectorTables")  # 삭제 가드와 동일 normalizer(drift 0)
    if not vt_names or remote:
        return [], []
    cols = (
        (
            await db.execute(
                select(Collection)
                .where(Collection.name.in_(vt_names))
                .options(
                    selectinload(Collection.embedding_model).selectinload(ModelConfig.provider)
                )
            )
        )
        .scalars()
        .all()
    )
    rag_collections: list[dict] = []
    for col in cols:
        entry = _rag_collection_entry(col)
        if entry is None:
            log.warning("rag collection %s skipped: embedding model/provider 불완전", col.name)
            continue
        rag_collections.append(entry)
    resolved = {rc["name"] for rc in rag_collections}
    unresolved = [n for n in vt_names if n not in resolved]
    if unresolved:
        log.warning(
            "rag vectorTables 미해석: %s (요청 %s → 해석 %s)",
            unresolved,
            vt_names,
            sorted(resolved),
        )
    return rag_collections, unresolved
