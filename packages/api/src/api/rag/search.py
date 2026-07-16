"""rag.search — 라우트 핸들러(스펙 381 분할). 서비스/헬퍼는 shared."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_principal
from ..db import get_session
from ..models import (
    User,
)
from ..schemas import (
    CollectionSearchIn,
    CollectionSearchOut,
    SearchHit,
)
from .shared import (
    _load_collection,
    resolve_search_collection,
    router,
)


@router.post("/{cid}/search", response_model=CollectionSearchOut)
async def search_collection(
    cid: uuid.UUID,
    body: CollectionSearchIn,
    session: AsyncSession = Depends(get_session),
    _principal: User | str = Depends(current_principal),
) -> CollectionSearchOut:
    """retrieval 시험 — 단일 컬렉션에 질의를 던져 상위 청크를 받는다(에이전트 채팅 불요).

    **핵심**: 인-챗 도구(`build_rag_tool`)와 **같은 코어**(`runtime.search_collections`)를 호출한다 —
    평행 구현을 새로 짜면 drift나 "엔드포인트는 초록인데 채팅은 다름"이 된다(스펙 072). 등록 직후
    같은 컬렉션에 질의를 던져 retrieval 품질을 즉석 확인하는 수단(사용자 보고 '테스트 방법이 없어' 공백).

    완전성 검사(가드): embedding 모델/provider가 불완전하면 검색 불가 → 400(graceful). 차원 drift는
    health(가드3)가 담당. api_key는 백엔드에서만 복호화하며 응답에 절대 포함하지 않는다.
    """
    from .. import runtime  # 지연 임포트(런타임 의존 격리)

    # 사용은 전부 공용(스펙 172) — 로그인한 누구나 검색 가능(current_principal이 익명은 401 차단).
    # 관리(수정·삭제·인제스트)는 여전히 소유자만(assert_may_manage). 존재 404만 유지.
    gate = await _load_collection(session, cid)
    if gate is None:
        raise HTTPException(status_code=404, detail="not found")
    col = await resolve_search_collection(session, cid)
    try:
        hits = await runtime.search_collections([col], body.query, body.top_k)
    except runtime.RagSearchError as exc:
        # 무중단 재인덱싱(스펙 313): 검색은 재인덱싱에 막히지 않으므로 locked(409)는 더 이상 발생하지
        # 않는다. 빈 질의는 스키마(min_length=1)가 먼저 막으므로 여기 도달하는 건 embed/db 실패 — 502.
        raise HTTPException(status_code=502, detail=exc.tool_msg) from exc
    return CollectionSearchOut(
        query=body.query,
        top_k=body.top_k,
        results=[SearchHit(**h) for h in hits],
    )
