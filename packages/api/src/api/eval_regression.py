"""자동 회귀 트리거(스펙 241, AgentOps B) — eval_runs.py에서 분할(스펙 399 P5).

trigger_auto_regression(구 CC 13)은 후보 수집(_regression_candidates)·버전 dedupe 술어
(_has_regressed)·단건 시작(_start_auto_run) 추출로 분해. **명시 개선(스펙 399, codex P1)**:
활성화 시점 버전(opened_version)을 캡처해 `_execute_run(..., version=opened_version)`으로
명시 전달 — 구코드는 version=None으로 스폰해 실행기가 **실행 시점** active를 다시 읽었고,
빠른 재오픈/롤백이 끼면 행에 박제된 agent_version과 실제 평가한 버전이 갈라졌다(372 "평가한
것==배포한 것" seam의 자동 회귀판 구멍 — verify_373은 수동 지정 경로만 닫음).
파사드는 eval_runs.py(재수출).
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .background import spawn
from .db import SessionLocal
from .eval_admission import _admission_check
from .eval_common import log
from .eval_env import _env_snapshot
from .eval_execution import _execute_run
from .eval_guards import _member_run_guard
from .models import Agent, EvalDataset, EvalRun, User
from .ownership import is_privileged, may_manage, owner_of


async def _regression_candidates(
    session: AsyncSession, agent_pk: uuid.UUID, actor: User | str
) -> list[EvalDataset]:
    """회귀 자산 후보 — 실행 이력 있는 문제집 ∪ 수확 문제집, 최근 순 최대 3개(비용 캡 — 서빙
    모델이 실모델일 수 있음). 소유권 게이트(codex 241 #1): 수동 start_run은 assert_may_manage를
    요구하므로 자동 경로도 활성화 주체가 관리 가능한 문제집만(우회 차단)."""
    ran_ds = select(EvalRun.dataset_id).where(EvalRun.agent_pk == agent_pk)
    candidates = (
        (
            await session.execute(
                select(EvalDataset)
                .where(
                    EvalDataset.kind == "agent",
                    or_(EvalDataset.id.in_(ran_ds), EvalDataset.source_agent_pk == agent_pk),
                )
                .order_by(EvalDataset.updated_at.desc())
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    return [ds for ds in candidates if may_manage(ds, actor)]


async def _has_regressed(
    session: AsyncSession, ds: EvalDataset, agent_pk: uuid.UUID, version: str | None
) -> bool:
    """버전당 1회 dedupe(codex 241 #2) — 같은 버전을 재활성화(연타·되돌림 반복)해도 이미
    그 버전의 자동 회귀 런이 있으면 스킵(실모델 비용 폭주 차단). 새 버전만 새 런."""
    dup = (
        await session.execute(
            select(func.count(EvalRun.id)).where(
                EvalRun.dataset_id == ds.id,
                EvalRun.agent_pk == agent_pk,
                EvalRun.agent_version == version,
                EvalRun.env["trigger"].astext == "activate",
            )
        )
    ).scalar_one()
    return bool(dup)


async def _start_auto_run(
    session: AsyncSession,
    ds: EvalDataset,
    agent: Agent,
    actor: User | str,
    run_env: dict,
    opened_version: str | None,
) -> bool:
    """단건 자동 회귀 시작 — 게이트 사슬(admission→비용 가드) 통과 시 행 commit 후 spawn.

    승인 판정은 수동 경로와 공유(스펙 377) — 빈 문제집·running 중복은 조용히 스킵. 비특권은
    비용 가드(347)도 조용히 스킵(판정식은 _member_run_guard 단일 — 반응만 다름)."""
    n_cases, reason = await _admission_check(session, ds.id)
    if reason:
        return False
    if not is_privileged(actor):
        try:
            await _member_run_guard(session, actor, ds.id, 0)
        except HTTPException:
            log.info("자동 회귀 스킵(비용 가드): dataset=%s agent=%s", ds.id, agent.id)
            return False
    run = EvalRun(
        dataset_id=ds.id,
        agent_pk=agent.id,
        agent_name=agent.name,
        status="running",
        total=n_cases,
        owner_id=owner_of(actor),
        agent_version=opened_version,
        env=run_env,
    )
    session.add(run)
    await session.commit()
    # 버전 핀(스펙 399 명시 개선) — 행에 박제한 opened_version 그대로 실행(실행 시점 active 재읽기
    # 금지). 행 박제와 실제 평가 버전이 항상 일치(372 seam의 자동 회귀판 봉합).
    spawn(_execute_run(run.id, ds.id, agent.id, actor, version=opened_version))
    return True


async def trigger_auto_regression(
    agent_pk: uuid.UUID, actor: User | str, opened_version: str | None = None
) -> int:
    """버전 활성화 시 자동 회귀(스펙 241, AgentOps B) — 이 에이전트의 회귀 자산(실행 이력 있는 문제집
    ∪ 수확 문제집)을 자동 재실행. 최근 순 최대 3개(비용 캡 — 서빙 모델이 실모델일 수 있음).

    fire-and-forget 계약: 어떤 실패도 활성화를 깨지 않는다(로그만). 케이스 0·이미 running·비특권
    비용 가드 거부는 조용히 스킵. 각 런은 240 박제 + env.trigger="activate"(자동 회귀 식별).
    **경계**: 서빙 config 실측이라 "배포 전" 게이트가 아님 — 회귀 발견 시 revert가 대응 경로(스펙 241).
    """
    started = 0
    try:
        async with SessionLocal() as session:
            agent = await session.get(Agent, agent_pk)
            if agent is None:
                return 0
            candidates = await _regression_candidates(session, agent_pk, actor)
            if not candidates:
                return 0
            if opened_version is None:
                # 호출부가 이벤트 버전을 안 넘긴 경우의 폴백 — 태스크 실행 시점 active(구 동작보다는
                # 좁지만, 이벤트 버전 고정은 인자 관통이 정본. codex 399 적대: 연속 오픈 race).
                opened_version = agent.active_version
            run_env = await _env_snapshot(session, agent, None)
            run_env["trigger"] = "activate"
            for ds in candidates:
                if await _has_regressed(session, ds, agent_pk, opened_version):
                    continue
                if await _start_auto_run(session, ds, agent, actor, run_env, opened_version):
                    started += 1
        if started:
            log.info("자동 회귀 시작(스펙 241): agent=%s runs=%d", agent_pk, started)
    except Exception:
        log.exception("자동 회귀 트리거 실패(활성화는 정상 진행): agent=%s", agent_pk)
    return started
