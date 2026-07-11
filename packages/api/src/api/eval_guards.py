"""비특권 비용 가드·배경 작업 락(스펙 178, 스펙 291 분할).

**_active_jobs는 이 모듈이 유일 정의** — 다른 모듈은 반드시 여기서 import한다(재선언 금지).
모듈별 재선언은 락을 갈라 중복 생성/출제 TOCTOU를 부활시킨다(스펙 178 codex #1·#2 회귀).
add/discard 짝 불변식: 락을 동기 획득한 쪽(엔드포인트)이 실패 시 해제까지 책임진다.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EvalCase, EvalDataset, EvalRun
from .ownership import owner_of

# 스펙 178 비용 가드 — 비특권(멤버) 자율 실행이 실모델을 폭주시키지 않게. 특권(admin)은 무제한.
_MEMBER_MAX_CONCURRENT_RUNS = 2  # 유저당 동시 running run 상한(전 문제집 합산)
_MEMBER_MAX_RUN_WORK = (
    60  # 1회 실행 LLM 호출 상한 = models × (cases + llm_judge 기준 수)(codex 178)
)
_MEMBER_MAX_CONCURRENT_JOBS = (
    2  # 유저당 동시 배경 LLM 작업(생성/출제) 상한(codex 178: generate/suggest flood 차단)
)

# 진행 중 백그라운드 작업 락(codex 143 — description 접미 검사는 PATCH로 우회/오작동 가능).
# create_task와 수명이 같아 재시작 시 자동 소멸(잔류 description은 sweep이 정리).
_active_jobs: set = set()


async def _member_run_guard(
    session: AsyncSession, user, dataset_id: uuid.UUID, n_models: int
) -> None:
    """비특권 실행 비용 가드(스펙 178, codex 반영). 특권은 호출 전 단락. per-user advisory 락으로
    동시성 확인+삽입 사이 TOCTOU를 직렬화(codex #3), work는 judge 호출까지 포함(codex #5)."""
    owner = owner_of(user)
    # per-user 직렬화 — 병렬 요청이 my_running<2를 동시에 보고 상한을 넘기는 race 차단. xact 종료 시 해제.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"eval-run:{owner}"}
    )
    my_running = (
        await session.execute(
            select(func.count(EvalRun.id)).where(
                EvalRun.owner_id == owner, EvalRun.status == "running"
            )
        )
    ).scalar_one()
    if my_running >= _MEMBER_MAX_CONCURRENT_RUNS:
        raise HTTPException(
            status_code=429,
            detail=f"동시 실행 한도({_MEMBER_MAX_CONCURRENT_RUNS})에 도달했습니다 — 진행 중 실행이 끝나면 다시 시도하세요",
        )
    # work = 실 LLM 호출량 ≈ models × (케이스 + 케이스별 llm_judge 기준 수). judge 누락 보정(codex #5).
    asserts_rows = (
        (await session.execute(select(EvalCase.asserts).where(EvalCase.dataset_id == dataset_id)))
        .scalars()
        .all()
    )
    n_cases = len(asserts_rows)
    judge_count = sum(
        1
        for row in asserts_rows
        for a in (row or [])
        if isinstance(a, dict) and a.get("type") == "llm_judge"
    )
    work = max(1, n_models) * (n_cases + judge_count)
    if work > _MEMBER_MAX_RUN_WORK:
        raise HTTPException(
            status_code=422,
            detail=f"실행 규모(모델 {max(1, n_models)} × [케이스 {n_cases} + 판정 {judge_count}] = {work})가 한도 {_MEMBER_MAX_RUN_WORK}를 넘습니다 — 케이스·판정·모델 수를 줄이세요",
        )


async def _member_job_guard(
    session: AsyncSession, user, exclude_id: uuid.UUID | None = None
) -> None:
    """비특권 배경 LLM 작업(문제집 생성·AI 출제) 동시 상한(스펙 178, codex #1·#2). 특권은 호출 전 단락.
    진실원은 `_active_jobs`(동기 등록) — exclude_id는 이미 락을 잡은 현재 작업(세지 않음). 소유자별 합산."""
    active = {j for j in _active_jobs if j != exclude_id}
    if not active:
        return
    mine = (
        await session.execute(
            select(func.count(EvalDataset.id)).where(
                EvalDataset.owner_id == owner_of(user), EvalDataset.id.in_(active)
            )
        )
    ).scalar_one()
    if mine >= _MEMBER_MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"동시 생성·출제 한도({_MEMBER_MAX_CONCURRENT_JOBS})에 도달했습니다 — 진행 중 작업이 끝나면 다시 시도하세요",
        )


async def _helper_llm(session: AsyncSession) -> tuple[dict | None, str | None]:
    """도우미 LLM 해석 — (llm_cfg, 불가 사유). 기본 chat이 실모델일 때만(사용자 원칙)."""
    from . import crypto
    from .eval_suggest import is_mock_llm
    from .mem_config import _default_chat_model

    cm = await _default_chat_model(session)
    if cm is None or cm.provider is None or not cm.provider.base_url or not cm.model_id:
        return None, "기본 chat 모델이 없습니다 — 프로바이더·모델에서 기본 모델을 지정하세요"
    if is_mock_llm(cm.provider.base_url, cm.model_id):
        return (
            None,
            "기본 chat 모델이 mock입니다 — 실모델을 기본으로 지정하면 도우미가 활성화됩니다",
        )
    return {
        "base_url": cm.provider.base_url,
        "api_key": crypto.decrypt(cm.provider.api_key),
        "model_id": cm.model_id,
    }, None
