"""평가 라우터 공유 기반(스펙 291 분할) — router·404/검증 헬퍼·DatasetOut 조립·진행 판정.

허브 모듈: 전 eval_* 라우트 모듈이 여기서 **단일 router**를 import해 라우트를 등록한다.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_or_404
from .eval_harness import build_asserts
from .eval_schemas import DatasetOut
from .models import EvalDataset, User
from .ownership import assert_may_manage, may_manage
from .serializers import audit_of

log = logging.getLogger("api.eval")

router = APIRouter(prefix="/eval", tags=["eval"])

# 스펙 178: 평가는 소유 기반(컬렉션 패턴 = 읽기 공개·관리 소유자). require("eval",*) admin 게이트를
# 제거하고 current_principal + ownership.py 술어로 전환 — 멤버가 본인 문제집·본인 쓸 수 있는 에이전트를
# 자율 평가. 읽기(list/get)는 전 유저 공개(D1), 관리(생성/수정/삭제/실행)는 소유자만(비소유 404-fold).


def _is_generating(d: EvalDataset) -> bool:
    """진행 중 판정(단일 출처) — 진행 마커 2종(전부 접미): AI 출제(143/195)="… · AI 출제 중…",
    피드백 수확(209 P2)="… · 피드백 수확 중…". 컬렉션 통째 생성(142)의 "생성 중…" 접두 분기는
    스펙 329에서 기능과 함께 제거."""
    desc = d.description or ""
    return desc.endswith("AI 출제 중…") or desc.endswith("피드백 수확 중…")


def _dataset_out(d: EvalDataset, case_count: int, user: User | str) -> DatasetOut:
    """DatasetOut 단일 생성 경로(드리프트 0) — 인라인 통일. generating은 description 진행 마커를
    구조 필드로 승격(프론트는 bool만 소비 → 목록 배지·드로어 Skeleton·폴링)."""
    return DatasetOut(
        id=d.id,
        name=d.name,
        description=d.description,
        kind=d.kind,
        collection_id=d.collection_id,
        source_agent_pk=d.source_agent_pk,
        case_count=case_count,
        can_manage=may_manage(d.owner_id, user),
        generating=_is_generating(d),
        **audit_of(d),  # 감사 4값(스펙 344)
    )


def _validate_asserts(asserts: list) -> None:
    """선언 asserts를 저장 전에 검증 — build_asserts의 닫힌 집합·형식 규칙 그대로(단일 출처)."""
    try:
        build_asserts(asserts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _dataset_or_404(session: AsyncSession, dataset_id: uuid.UUID) -> EvalDataset:
    """문제집 조회 — 없으면 404(정본 get_or_404 위임, 스펙 297)."""
    return await get_or_404(session, EvalDataset, dataset_id, detail="dataset not found")


def _gate_harvest_read(ds: EvalDataset, user: User | str) -> None:
    """수확 문제집(source_agent_pk≠NULL)은 **소유자/admin만** 읽는다(codex P2 F1). eval 읽기는 본래 전원
    공개(178 D1)지만, 수확 케이스 input=사용자 세션 질문이라 세션 소유 스코프를 상속해야 한다(스펙 209 §B).
    일반 문제집(source_agent_pk=NULL)은 공개 유지. 비소유=404-fold(존재 비노출)."""
    if ds.source_agent_pk is not None:
        assert_may_manage(ds, user, not_found_detail="dataset not found")
