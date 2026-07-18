"""평가 런 생성·스케줄링 — eval_runs.py에서 분할(스펙 399 P4).

**202 계약 박제**(codex 399 최위험 축): running 행 commit → 배경 spawn(detach) → RunOut 반환.
_spawn_runs(구 B10)의 3분기 중복(행 생성·commit·spawn)은 행 빌더(_new_run_row) 추출로 접되
분기별 "commit 후 spawn" 순서는 각 분기에 그대로 남긴다(추출된 헬퍼가 spawn을 앞당기는 회귀
금지). 파사드는 eval_runs.py(재수출).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .background import spawn
from .eval_env import _model_env
from .eval_execution import _execute_group, _execute_run
from .eval_schemas import RunOut, RunStartIn
from .models import Agent, EvalRun, User
from .ownership import owner_of


def _new_run_row(
    *,
    dataset_id: uuid.UUID,
    agent: Agent | None,
    target_name: str | None,
    n_cases: int,
    user: User | str,
    agent_version: str | None,
    env: dict,
    model_name: str | None = None,
    group_id: uuid.UUID | None = None,
) -> EvalRun:
    """EvalRun(running) 행 빌더(스펙 399 분해) — 3분기 공통 필드 단일화. 생성만(commit·spawn은
    호출부 소유 — 202 계약의 순서는 _spawn_runs가 지킨다)."""
    return EvalRun(
        dataset_id=dataset_id,
        agent_pk=agent.id if agent else None,
        agent_name=target_name,
        model_name=model_name,
        group_id=group_id,
        status="running",
        total=n_cases,
        owner_id=owner_of(user),
        agent_version=agent_version,
        env=env,
    )


async def _spawn_runs(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    body: RunStartIn,
    user: User | str,
    agent: Agent | None,
    rag_collection: dict | None,
    target_name: str | None,
    models: list[str],
    n_cases: int,
    run_env: dict,
    agent_version: str | None,
) -> RunOut:
    """EvalRun 생성+커밋+배경 실행 3분기(단일 모델 오버라이드/비교 그룹/기본) — 대표 RunOut 반환."""
    if len(models) == 1:
        # 1개 선택=비교가 아니라 단순 모델 오버라이드 런(codex 141 #3 — 1열 그룹은 격자 의미 없음).
        assert (
            agent is not None
        )  # _validate_compare_models가 kind!=agent에 400 — models 있으면 agent 존재
        run = _new_run_row(
            dataset_id=dataset_id,
            agent=agent,
            target_name=target_name,
            n_cases=n_cases,
            user=user,
            agent_version=agent_version,
            env={**run_env, "model": await _model_env(session, models[0])},
            model_name=models[0],
        )
        session.add(run)
        await session.commit()
        spawn(
            _execute_run(
                run.id,
                dataset_id,
                agent.id,
                user,
                overrides={"model": models[0]},
                version=body.agent_version,
            )
        )
        return RunOut.model_validate(run)

    if models:
        assert (
            agent is not None
        )  # _validate_compare_models가 kind!=agent에 400 — models 있으면 agent 존재
        group_id = uuid.uuid4()
        model_envs = {m: await _model_env(session, m) for m in models}
        runs = [
            _new_run_row(
                dataset_id=dataset_id,
                agent=agent,
                target_name=target_name,
                n_cases=n_cases,
                user=user,
                agent_version=agent_version,
                env={**run_env, "model": model_envs[m]},
                model_name=m,
                group_id=group_id,
            )
            for m in models
        ]
        session.add_all(runs)
        await session.commit()
        spawn(
            _execute_group(
                [(r.id, r.model_name) for r in runs],
                dataset_id,
                agent.id,
                user,
                version=body.agent_version,
            )
        )
        return RunOut.model_validate(runs[0])

    run = _new_run_row(
        dataset_id=dataset_id,
        agent=agent,
        target_name=target_name,
        n_cases=n_cases,
        user=user,
        agent_version=agent_version,
        env=run_env,
    )
    session.add(run)
    await session.commit()
    spawn(
        _execute_run(
            run.id,
            dataset_id,
            agent.id if agent else None,
            user,
            rag_collection=rag_collection,
            version=body.agent_version,
        )
    )
    return RunOut.model_validate(run)
