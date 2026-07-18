"""실행/성적표 라우트 — **파사드**(스펙 137·140·141·240·241·242, 291→399 분할).

스펙 399: 실행 미니앱을 가족별 형제로 해체 — eval_execution(배경 러너·상태 commit 순서 소유) ·
eval_admission(접수 게이트 — 판정 단일 출처) · eval_scheduling(런 생성·202 commit-before-spawn
계약 소유) · eval_regression(자동 회귀 — 버전 핀 포함) · eval_recovery(좀비 스윕). 이 파일은
라우트 3개(start_run·list_runs·get_run)와 재수출만 갖는다. eval_routes 파사드 계약 무변경.
"""

import uuid

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_principal
from .db import get_or_404, get_session
from .eval_admission import (  # noqa: F401
    _admission_check,
    _assert_run_admission,
    _resolve_pinned_version,
    _resolve_run_target,
    _validate_compare_models,
)
from .eval_common import _dataset_or_404, router
from .eval_env import _env_snapshot
from .eval_execution import _execute_group, _execute_run  # noqa: F401
from .eval_guards import _member_run_guard
from .eval_recovery import sweep_zombie_datasets, sweep_zombie_runs  # noqa: F401
from .eval_regression import trigger_auto_regression  # noqa: F401
from .eval_scheduling import _spawn_runs
from .eval_schemas import CaseResultOut, RunDetailOut, RunOut, RunStartIn
from .models import EvalCaseResult, EvalDataset, EvalRun, User
from .ownership import assert_may_manage, is_privileged, may_manage


@router.post("/datasets/{dataset_id}/runs", response_model=RunOut, status_code=202)
async def start_run(
    dataset_id: uuid.UUID,
    body: RunStartIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> RunOut:
    """시험 실행 시작 — EvalRun(running) 즉시 반환, 백그라운드에서 케이스 순차 실행(폴링으로 조회)."""
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(
        ds, user, not_found_detail="dataset not found"
    )  # 본인 문제집만 실행(비소유 404-fold)
    agent, rag_collection, target_name = await _resolve_run_target(session, ds, body, user)
    n_cases = await _assert_run_admission(session, dataset_id)
    models = await _validate_compare_models(session, ds, body)

    # 스펙 178 비용 가드(비특권 자율 실행) — 특권은 무제한. advisory 락+judge 포함 work(codex 반영).
    if not is_privileged(user):
        await _member_run_guard(session, user, dataset_id, len(models))

    pinned_cfg = await _resolve_pinned_version(session, agent, body, user)

    # 버전 귀속+환경 기록(스펙 240) — **실행한 버전**(지정 시 지정 버전, 아니면 활성)과 그 버전 config
    # 기준의 경량 환경을 모든 런에 박제(스펙 242 의미 확장).
    run_env = await _env_snapshot(session, agent, rag_collection, cfg_override=pinned_cfg)
    agent_version = (body.agent_version or agent.active_version) if agent is not None else None

    return await _spawn_runs(
        session,
        dataset_id=dataset_id,
        body=body,
        user=user,
        agent=agent,
        rag_collection=rag_collection,
        target_name=target_name,
        models=models,
        n_cases=n_cases,
        run_env=run_env,
        agent_version=agent_version,
    )


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    dataset_id: uuid.UUID | None = None,  # 문제집 필터(스펙 138 — 추이/비교용)
    group_id: uuid.UUID
    | None = None,  # 비교 그룹 전량 조회(스펙 141 — 최근 50 컷에 그룹이 잘리면 부분 격자, codex #1)
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> list[RunOut]:
    q = (
        select(EvalRun, EvalDataset.name)
        .join(EvalDataset, EvalDataset.id == EvalRun.dataset_id)
        .order_by(EvalRun.started_at.desc())
    )
    # 그룹은 최대 6건 — limit 불요
    q = q.where(EvalRun.group_id == group_id) if group_id is not None else q.limit(50)
    if dataset_id is not None:
        q = q.where(EvalRun.dataset_id == dataset_id)
    rows = (await session.execute(q)).all()
    out = []
    for r, ds_name in rows:
        o = RunOut.model_validate(r)
        o.dataset_name = ds_name
        o.can_manage = may_manage(r.owner_id, user)
        out.append(o)
    return out


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> RunDetailOut:
    run = await get_or_404(session, EvalRun, run_id, detail="run not found")
    ds = await session.get(
        EvalDataset, run.dataset_id
    )  # 성적표 제목용(codex 137 #4 — 목록만 채우던 것)
    results = (
        (
            await session.execute(
                select(EvalCaseResult)
                .where(EvalCaseResult.run_id == run_id)
                .order_by(EvalCaseResult.created_at)
            )
        )
        .scalars()
        .all()
    )
    # RunDetailOut을 run으로 직접 model_validate하면 안 된다 — results 필드명이 ORM lazy 관계
    # EvalRun.results와 겹쳐 from_attributes가 비동기 밖 lazy load를 시도, MissingGreenlet 500
    # (129와 같은 부류 — e2e가 포착). RunOut(results 없음)으로 안전 추출 후 명시 구성.
    base = RunOut.model_validate(run)
    return RunDetailOut(
        **base.model_dump(),
        results=[CaseResultOut.model_validate(r) for r in results],
    ).model_copy(
        update={
            "dataset_name": ds.name if ds else None,
            "can_manage": may_manage(run.owner_id, user),
        }
    )
