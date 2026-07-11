"""실행/성적표 라우트 + 백그라운드 러너(스펙 137·140·141·240·241·242, 스펙 291 분할).

start_run은 관심사별 헬퍼 5개(대상 해석/승인 게이트/모델 검증/버전 해석/런 생성)로 분해(스펙 291).
배경 태스크는 요청 세션과 수명이 달라 SessionLocal(팩토리)을 직접 연다.
"""

import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_principal
from .background import spawn
from .db import SessionLocal, get_or_404, get_session
from .eval_common import _dataset_or_404, log, router
from .eval_env import _env_snapshot, _model_env
from .eval_guards import _active_jobs, _member_run_guard
from .eval_harness import EvalCase as HarnessCase
from .eval_harness import build_asserts, run_eval
from .eval_runner import eval_run_agent
from .eval_schemas import CaseResultOut, RunDetailOut, RunOut, RunStartIn
from .models import Agent, EvalCase, EvalCaseResult, EvalDataset, EvalRun, User
from .ownership import assert_may_manage, is_privileged, may_manage, may_use_agent, owner_of


async def _execute_run(
    run_id: uuid.UUID,
    dataset_id: uuid.UUID,
    agent_pk,  # noqa: ANN001 — uuid.UUID | None이나 None은 rag 분기 전용: 주석 시 eval_run_agent(UUID) 호출이 mypy arg-type(스펙 292 P1 보고)
    principal: User | str,
    rag_collection: dict | None = None,
    overrides: dict | None = None,
    version: str | None = None,
) -> None:
    """백그라운드 실행(batch runner 미러) — 케이스 **순차**(실모델 rate-limit·격리), 상태머신
    running→ok|error. kind=rag면 rag_collection으로 검색 러너(스펙 140), 아니면 agent 러너.
    케이스/러너 실패는 하네스가 error 관측으로 접어 전체는 계속(조용한 초록 금지)."""
    try:
        async with SessionLocal() as s:
            rows = (
                (
                    await s.execute(
                        select(EvalCase)
                        .where(EvalCase.dataset_id == dataset_id)
                        .order_by(EvalCase.order_idx, EvalCase.created_at)
                    )
                )
                .scalars()
                .all()
            )
            cases = [
                # 스펙 195: 성적표 식별자(case_name)에 **질문**을 넣는다 — DB name은 내부 해시라
                # 성적표에 뜨면 유저가 못 알아본다. 표시 상한 200자.
                HarnessCase(
                    name=(c.input or c.name)[:200],
                    input=c.input,
                    asserts=build_asserts(c.asserts),
                    meta={"raw_asserts": c.asserts},
                )
                for c in rows
            ]

        # LLM-judge 심판 모델(스펙 139) — 기본 chat 모델(is_default)만 직접 해석. default_mem_cfg는
        # embedding까지 요구해 embedding 미설정이 judge를 인질로 잡는다(codex 139 #3) → chat만 본다.
        # 미설정이면 judge 전부 실패(fail-closed) — run_llm_judge가 사유를 남긴다.
        from . import crypto
        from .eval_judge import run_llm_judge
        from .mem_config import _default_chat_model

        async with SessionLocal() as s:
            _cm = await _default_chat_model(s)
        judge_llm = None
        if _cm is not None and _cm.provider is not None and _cm.provider.base_url and _cm.model_id:
            judge_llm = {
                "base_url": _cm.provider.base_url,
                "api_key": crypto.decrypt(_cm.provider.api_key),
                "model_id": _cm.model_id,
            }

        async def run_fn(case: HarnessCase) -> dict:
            if rag_collection is not None:
                from .eval_runner import eval_run_rag

                obs = await eval_run_rag(rag_collection, case.input)
            else:
                # 위임 총량 예산 루트 주입(스펙 256, codex 후속) — 평가도 조율형 팬아웃(A→B/C/D…)이
                # 가능하므로 chat 루트와 대칭으로 카운터를 심어 breadth 폭주를 DELEGATION_MAX_TOTAL로 상한.
                # 케이스마다 새 예산(케이스 간 독립).
                obs = await eval_run_agent(
                    agent_pk,
                    case.input,
                    principal,
                    overrides,
                    version=version,
                    delegation_budget={"n": 0},
                )
            # 이 케이스의 llm_judge 기준만 순차 심판(스펙 139) — 결과를 obs에 주입, scorer는 읽기만.
            criteria = [
                arg
                for a in case.meta.get("raw_asserts", [])
                if isinstance(a, dict) and a.get("type") == "llm_judge" and (arg := a.get("arg"))
            ]
            if criteria:
                judge: dict = {}
                for crit in criteria:
                    judge[crit] = await run_llm_judge(
                        case.input, obs.get("output", ""), crit, judge_llm
                    )
                obs["judge"] = judge
            return obs

        report = await run_eval(cases, run_fn)

        async with SessionLocal() as s:
            run = await s.get(EvalRun, run_id)
            if run is None:
                return
            for result in report.results:
                s.add(
                    EvalCaseResult(
                        run_id=run_id,
                        case_name=result.name,
                        case_passed=result.passed,
                        details=[list(d) for d in result.details],
                        obs=result.obs,
                    )
                )
            run.status = "ok"
            run.score = report.score
            run.passed = report.passed
            run.total = report.total
            run.summary = {"summary": report.summary()}
            run.finished_at = datetime.now(UTC)
            await s.commit()
    except Exception as exc:
        try:
            async with SessionLocal() as s:
                run = await s.get(EvalRun, run_id)
                if run is not None:
                    run.status = "error"
                    run.error = str(exc)[:1000]
                    run.finished_at = datetime.now(UTC)
                    await s.commit()
        except Exception:
            pass


async def _execute_group(
    specs: list[tuple],
    dataset_id: uuid.UUID,
    agent_pk: uuid.UUID,
    principal: User | str,
    version: str | None = None,
) -> None:
    """모델 비교 그룹 실행(스펙 141) — (run_id, model_name)들을 **순차**로(로컬 LLM 과점유 방지).
    개별 런 실패는 _execute_run이 error로 박제하고 다음 모델은 계속."""
    for run_id, model_name in specs:
        await _execute_run(
            run_id,
            dataset_id,
            agent_pk,
            principal,
            overrides={"model": model_name} if model_name else None,
            version=version,
        )


async def trigger_auto_regression(agent_pk: uuid.UUID, actor: User | str) -> int:
    """버전 활성화 시 자동 회귀(스펙 241, AgentOps B) — 이 에이전트의 회귀 자산(실행 이력 있는 문제집
    ∪ 수확 문제집)을 자동 재실행. 최근 순 최대 3개(비용 캡 — 서빙 모델이 실모델일 수 있음).

    fire-and-forget 계약: 어떤 실패도 활성화를 깨지 않는다(로그만). 케이스 0·이미 running·비특권
    비용 가드 거부는 조용히 스킵. 각 런은 240 박제 + env.trigger="activate"(자동 회귀 식별).
    **경계**: 서빙 config 실측이라 "배포 전" 게이트가 아님 — 회귀 발견 시 revert가 대응 경로(스펙 241).
    """
    started = 0
    try:
        async with SessionLocal() as session:
            from .models import Agent

            agent = await session.get(Agent, agent_pk)
            if agent is None:
                return 0
            ran_ds = select(EvalRun.dataset_id).where(EvalRun.agent_pk == agent_pk)
            candidates = (
                (
                    await session.execute(
                        select(EvalDataset)
                        .where(
                            EvalDataset.kind == "agent",
                            or_(
                                EvalDataset.id.in_(ran_ds), EvalDataset.source_agent_pk == agent_pk
                            ),
                        )
                        .order_by(EvalDataset.updated_at.desc())
                        .limit(3)
                    )
                )
                .scalars()
                .all()
            )
            if not candidates:
                return 0
            # 소유권 게이트(codex 241 #1) — 수동 start_run은 assert_may_manage(ds)를 요구한다. 자동
            # 경로가 남의 문제집(내 에이전트로 남이 실행한 이력)을 실행하면 그 우회가 된다 — 활성화
            # 주체가 관리 가능한 문제집만.
            candidates = [ds for ds in candidates if may_manage(ds, actor)]
            if not candidates:
                return 0
            run_env = await _env_snapshot(session, agent, None)
            run_env["trigger"] = "activate"
            for ds in candidates:
                # 버전당 1회 dedupe(codex 241 #2) — 같은 버전을 재활성화(연타·되돌림 반복)해도 이미
                # 그 버전의 자동 회귀 런이 있으면 스킵(실모델 비용 폭주 차단). 새 버전만 새 런.
                dup = (
                    await session.execute(
                        select(func.count(EvalRun.id)).where(
                            EvalRun.dataset_id == ds.id,
                            EvalRun.agent_pk == agent_pk,
                            EvalRun.agent_version == agent.active_version,
                            EvalRun.env["trigger"].astext == "activate",
                        )
                    )
                ).scalar_one()
                if dup:
                    continue
                n_cases = (
                    await session.execute(
                        select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id)
                    )
                ).scalar_one()
                if n_cases == 0:
                    continue
                running = (
                    await session.execute(
                        select(func.count(EvalRun.id)).where(
                            EvalRun.dataset_id == ds.id, EvalRun.status == "running"
                        )
                    )
                ).scalar_one()
                if running:
                    continue
                if not is_privileged(actor):
                    try:
                        await _member_run_guard(session, actor, ds.id, 0)
                    except HTTPException:
                        log.info("자동 회귀 스킵(비용 가드): dataset=%s agent=%s", ds.id, agent_pk)
                        continue
                run = EvalRun(
                    dataset_id=ds.id,
                    agent_pk=agent.id,
                    agent_name=agent.name,
                    status="running",
                    total=n_cases,
                    owner_id=owner_of(actor),
                    agent_version=agent.active_version,
                    env=run_env,
                )
                session.add(run)
                await session.commit()
                spawn(_execute_run(run.id, ds.id, agent.id, actor))
                started += 1
        if started:
            log.info("자동 회귀 시작(스펙 241): agent=%s runs=%d", agent_pk, started)
    except Exception:
        log.exception("자동 회귀 트리거 실패(활성화는 정상 진행): agent=%s", agent_pk)
    return started


async def _resolve_run_target(
    session: AsyncSession, ds: EvalDataset, body: RunStartIn, user: User | str
) -> tuple[Agent | None, dict | None, str | None]:
    """kind별 실행 대상 해석(스펙 140) — (agent, rag_collection, target_name).
    교차 대상은 400(codex 140 #1 — 조용한 무시는 "다른 대상을 시험했다"는 오해를 만든다)."""
    if body.agent_id is not None and body.collection_id is not None:
        raise HTTPException(
            status_code=400, detail="agent_id와 collection_id는 동시에 줄 수 없습니다"
        )
    if ds.kind == "rag":
        # 스펙 193: 문제집에 고정된 컬렉션 우선. body 값은 하위호환·구버전 첫 실행(lazy 고정)용.
        coll_id = ds.collection_id or body.collection_id
        if coll_id is None:
            raise HTTPException(status_code=400, detail="RAG 문제집은 collection_id가 필요합니다")
        from .rag import resolve_search_collection

        rag_collection = await resolve_search_collection(session, coll_id)  # 404/400 자체 처리
        if (
            ds.collection_id is None
        ):  # 구버전 문제집: 첫 실행 때 고른 컬렉션을 고정(이후 재선택 불필요)
            ds.collection_id = coll_id
        return None, rag_collection, f"RAG · {rag_collection['name']}"
    if body.agent_id is None:
        raise HTTPException(status_code=400, detail="에이전트 문제집은 agent_id가 필요합니다")
    agent = await session.get(Agent, body.agent_id)
    # 스펙 178 구멍#1 봉합: 쓸 수 있는 에이전트만 평가 대상(남의 private을 UUID로 지정해도 404-fold).
    if agent is None or not may_use_agent(agent, user):
        raise HTTPException(status_code=404, detail="agent not found")
    return agent, None, agent.name


async def _assert_run_admission(
    session: AsyncSession, ds: EvalDataset, dataset_id: uuid.UUID
) -> int:
    """실행 승인 게이트 3종(생성 중 409 · 빈 문제집 400 · 중복 실행 409) — 케이스 수 반환."""
    if dataset_id in _active_jobs or (ds.description or "").startswith("생성 중"):
        # 골든 생성/출제 진행 중 실행 금지(codex 142/143) — 락 우선, description은 재시작 잔류용 보조.
        raise HTTPException(
            status_code=409, detail="문제 생성이 진행 중입니다 — 완료 후 실행하세요"
        )
    n_cases = (
        await session.execute(
            select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset_id)
        )
    ).scalar_one()
    if n_cases == 0:
        raise HTTPException(status_code=400, detail="케이스가 없는 문제집은 실행할 수 없습니다")
    # 중복 실행 게이트(codex 137 #2) — 같은 문제집에 running이 있으면 409(더블클릭·다중 탭이
    # 실모델 호출을 N배로 만드는 사고 차단. admin 전용이어도 비용 사고는 사고).
    running = (
        await session.execute(
            select(func.count(EvalRun.id)).where(
                EvalRun.dataset_id == dataset_id, EvalRun.status == "running"
            )
        )
    ).scalar_one()
    if running:
        raise HTTPException(
            status_code=409, detail="이 문제집은 이미 실행 중입니다 — 완료 후 다시 시도하세요"
        )
    return n_cases


async def _validate_compare_models(
    session: AsyncSession, ds: EvalDataset, body: RunStartIn
) -> list[str]:
    """모델 비교(스펙 141, kind=agent 전용) 사전 검증 — 정규화된 모델 목록 반환. 이름은 레지스트리
    chat 모델로 **사전 검증**: _load_context는 미존재 이름을 기본 모델로 만회하므로(설정 만회 함정 —
    스펙 089와 동류) 여기서 안 막으면 "다른 모델로 조용히 시험"이 된다."""
    models: list[str] = [m.strip() for m in body.models if m and m.strip()]
    if not models:
        return models
    if ds.kind != "agent":
        raise HTTPException(status_code=400, detail="모델 비교는 에이전트 문제집에서만 가능합니다")
    if len(set(models)) != len(models):
        raise HTTPException(status_code=400, detail="모델 이름이 중복되었습니다")
    from .models import ModelConfig

    rows = (
        (
            await session.execute(
                select(ModelConfig.name).where(
                    ModelConfig.kind == "chat", ModelConfig.name.in_(models)
                )
            )
        )
        .scalars()
        .all()
    )
    missing = sorted(set(models) - set(rows))
    if missing:
        raise HTTPException(
            status_code=400, detail=f"레지스트리에 없는 chat 모델: {', '.join(missing)}"
        )
    return models


async def _resolve_pinned_version(
    session: AsyncSession, agent: Agent | None, body: RunStartIn, user: User | str
) -> dict | None:
    """버전 지정 평가(스펙 242) — 지정 시 그 버전 존재 검증 후 config 반환(초안=배포 전 게이트).
    미지정=None(활성 버전 config 사용)."""
    if body.agent_version is None:
        return None
    if agent is None:
        raise HTTPException(
            status_code=400, detail="agent_version은 에이전트 문제집에서만 사용합니다"
        )
    if not may_manage(agent, user):
        # 초안=미공개 작업본(codex 242 #2) — 버전 지정 평가는 그 에이전트 관리 권한 필요.
        raise HTTPException(
            status_code=403, detail="버전 지정 평가는 이 에이전트를 관리할 수 있어야 합니다"
        )
    from .models import AgentVersion

    vrow = (
        await session.execute(
            select(AgentVersion).where(
                AgentVersion.agent_pk == agent.id, AgentVersion.version == body.agent_version
            )
        )
    ).scalar_one_or_none()
    if vrow is None:
        raise HTTPException(
            status_code=404, detail=f"버전을 찾을 수 없습니다: {body.agent_version}"
        )
    return dict(vrow.config or {})


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
        run = EvalRun(
            dataset_id=dataset_id,
            agent_pk=agent.id,
            agent_name=target_name,
            model_name=models[0],
            status="running",
            total=n_cases,
            owner_id=owner_of(user),
            agent_version=agent_version,
            env={**run_env, "model": await _model_env(session, models[0])},
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
            EvalRun(
                dataset_id=dataset_id,
                agent_pk=agent.id,
                agent_name=target_name,
                model_name=m,
                group_id=group_id,
                status="running",
                total=n_cases,
                owner_id=owner_of(user),
                agent_version=agent_version,
                env={**run_env, "model": model_envs[m]},
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

    run = EvalRun(
        dataset_id=dataset_id,
        agent_pk=agent.id if agent else None,
        agent_name=target_name,
        status="running",
        total=n_cases,
        owner_id=owner_of(user),
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
    n_cases = await _assert_run_admission(session, ds, dataset_id)
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


async def sweep_zombie_datasets() -> int:
    """startup 정리(codex 142) — 생성 백그라운드 태스크는 재시작을 못 넘기므로, 부팅 시점의
    "생성 중…" description은 전부 죽은 생성이다. 정직 박제(영원한 '생성 중' 방지)."""
    async with SessionLocal() as s:
        rows = (
            (await s.execute(select(EvalDataset).where(EvalDataset.description.like("생성 중%"))))
            .scalars()
            .all()
        )
        for dataset in rows:
            dataset.description = "생성 중단(서버 재시작) — 삭제 후 다시 생성하세요"
        # AI 출제(스펙 143)도 같은 create_task라 재시작에 죽는다 — 접미 상태를 중단 박제.
        rows2 = (
            (
                await s.execute(
                    select(EvalDataset).where(EvalDataset.description.like("%AI 출제 중…"))
                )
            )
            .scalars()
            .all()
        )
        for dataset in rows2:
            dataset.description = (dataset.description or "").replace(
                "AI 출제 중…", "AI 출제 중단(서버 재시작) — 다시 시도하세요"
            )
        if rows or rows2:
            await s.commit()
        return len(rows) + len(rows2)


async def sweep_zombie_runs() -> int:
    """startup 정리(codex 137 #1) — asyncio.create_task는 프로세스 재시작을 못 넘기므로, 부팅 시점에
    남아 있는 status='running'은 전부 죽은 실행이다. error로 박제해 "영원한 실행 중" 잔류를 막는다."""
    async with SessionLocal() as s:
        rows = (await s.execute(select(EvalRun).where(EvalRun.status == "running"))).scalars().all()
        for run in rows:
            run.status = "error"
            run.error = "서버 재시작으로 실행이 중단되었습니다 — 다시 실행하세요"
            run.finished_at = datetime.now(UTC)
        if rows:
            await s.commit()
        return len(rows)
