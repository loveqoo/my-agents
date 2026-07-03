"""평가 하네스 제품화 라우터 — 문제집/케이스 CRUD + 실행/성적표 (스펙 137, admin 보호).

authz는 admin(*,*)이 ("eval",*)을 커버(batch_routes 미러 — 1탄은 admin 전용이 안전 기본값,
member 개방은 후속 논의). asserts는 선언적 JSON → `eval_harness.build_asserts`가 **닫힌 type
집합**으로 검증(미지 type=400, 조용한 통과 금지 — 평가는 fail-closed).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .db import get_session
from .eval_harness import build_asserts
from .models import EvalCase, EvalDataset
from .ownership import owner_of

router = APIRouter(prefix="/eval", tags=["eval"])

_manage = Depends(authz.require("eval", "manage"))
_run_dep = Depends(authz.require("eval", "run"))


# ----------------------------- 스키마 -----------------------------
class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    kind: str = Field(default="agent", pattern="^(agent|rag)$")


class DatasetOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    kind: str
    case_count: int = 0


class CaseIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=4000)  # 모델 프롬프트로 들어감 — 폭주 상한(codex 137 #3)
    asserts: list = Field(default_factory=list, max_length=20)  # 채점 기준 개수 상한
    order_idx: int = Field(default=0, ge=0, le=10_000)


class CaseOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    input: str
    asserts: list
    order_idx: int
    model_config = {"from_attributes": True}


def _validate_asserts(asserts: list) -> None:
    """선언 asserts를 저장 전에 검증 — build_asserts의 닫힌 집합·형식 규칙 그대로(단일 출처)."""
    try:
        build_asserts(asserts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def _dataset_or_404(session: AsyncSession, dataset_id: uuid.UUID) -> EvalDataset:
    ds = await session.get(EvalDataset, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return ds


# ----------------------------- 데이터셋 CRUD -----------------------------
@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(
    session: AsyncSession = Depends(get_session), user=_manage
) -> list[DatasetOut]:
    rows = (
        await session.execute(
            select(EvalDataset, func.count(EvalCase.id))
            .outerjoin(EvalCase, EvalCase.dataset_id == EvalDataset.id)
            .group_by(EvalDataset.id)
            .order_by(EvalDataset.name)
        )
    ).all()
    return [
        DatasetOut(id=d.id, name=d.name, description=d.description, kind=d.kind, case_count=n)
        for d, n in rows
    ]


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def create_dataset(
    body: DatasetIn, session: AsyncSession = Depends(get_session), user=_manage
) -> DatasetOut:
    ds = EvalDataset(
        name=body.name, description=body.description, kind=body.kind, owner_id=owner_of(user)
    )
    session.add(ds)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 문제집이 이미 있습니다")
    return DatasetOut(id=ds.id, name=ds.name, description=ds.description, kind=ds.kind, case_count=0)


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    dataset_id: uuid.UUID,
    body: DatasetIn,
    session: AsyncSession = Depends(get_session),
    user=_manage,
) -> DatasetOut:
    ds = await _dataset_or_404(session, dataset_id)
    ds.name, ds.description, ds.kind = body.name, body.description, body.kind
    await session.commit()
    n = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id))
    ).scalar_one()
    return DatasetOut(id=ds.id, name=ds.name, description=ds.description, kind=ds.kind, case_count=n)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=_manage
) -> None:
    ds = await _dataset_or_404(session, dataset_id)
    await session.delete(ds)  # cases·runs CASCADE
    await session.commit()


# ----------------------------- 케이스 CRUD -----------------------------
@router.get("/datasets/{dataset_id}/cases", response_model=list[CaseOut])
async def list_cases(
    dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=_manage
) -> list[CaseOut]:
    await _dataset_or_404(session, dataset_id)
    rows = (
        await session.execute(
            select(EvalCase)
            .where(EvalCase.dataset_id == dataset_id)
            .order_by(EvalCase.order_idx, EvalCase.created_at)
        )
    ).scalars().all()
    return [CaseOut.model_validate(c) for c in rows]


@router.post("/datasets/{dataset_id}/cases", response_model=CaseOut, status_code=201)
async def create_case(
    dataset_id: uuid.UUID,
    body: CaseIn,
    session: AsyncSession = Depends(get_session),
    user=_manage,
) -> CaseOut:
    await _dataset_or_404(session, dataset_id)
    _validate_asserts(body.asserts)
    case = EvalCase(
        dataset_id=dataset_id, name=body.name, input=body.input,
        asserts=body.asserts, order_idx=body.order_idx,
    )
    session.add(case)
    await session.commit()
    return CaseOut.model_validate(case)


@router.patch("/cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID, body: CaseIn, session: AsyncSession = Depends(get_session), user=_manage
) -> CaseOut:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _validate_asserts(body.asserts)
    case.name, case.input, case.asserts, case.order_idx = (
        body.name, body.input, body.asserts, body.order_idx,
    )
    await session.commit()
    return CaseOut.model_validate(case)


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=_manage
) -> None:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    await session.delete(case)
    await session.commit()


# ----------------------------- 실행/성적표 (단계 ②) -----------------------------
import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from .db import SessionLocal  # noqa: E402
from .eval_harness import EvalCase as HarnessCase, run_eval  # noqa: E402
from .eval_runner import eval_run_agent  # noqa: E402
from .models import Agent, EvalCaseResult, EvalRun  # noqa: E402


class RunStartIn(BaseModel):
    agent_id: uuid.UUID  # agents.id (pk)


class RunOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None  # 목록 표시용(조인 채움)
    agent_name: str | None
    status: str
    score: float | None
    passed: int
    total: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    model_config = {"from_attributes": True}


class CaseResultOut(BaseModel):
    case_name: str
    case_passed: bool
    details: list
    obs: dict | None
    model_config = {"from_attributes": True}


class RunDetailOut(RunOut):
    results: list[CaseResultOut] = []


async def _execute_run(run_id: uuid.UUID, dataset_id: uuid.UUID, agent_pk: uuid.UUID, principal) -> None:
    """백그라운드 실행(batch runner 미러) — 케이스 **순차**(실모델 rate-limit·격리), 상태머신
    running→ok|error. 케이스/러너 실패는 하네스가 error 관측으로 접어 전체는 계속(조용한 초록 금지)."""
    try:
        async with SessionLocal() as s:
            rows = (
                await s.execute(
                    select(EvalCase)
                    .where(EvalCase.dataset_id == dataset_id)
                    .order_by(EvalCase.order_idx, EvalCase.created_at)
                )
            ).scalars().all()
            cases = [
                HarnessCase(name=c.name, input=c.input, asserts=build_asserts(c.asserts),
                            meta={"raw_asserts": c.asserts})
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
            obs = await eval_run_agent(agent_pk, case.input, principal)
            # 이 케이스의 llm_judge 기준만 순차 심판(스펙 139) — 결과를 obs에 주입, scorer는 읽기만.
            criteria = [a.get("arg") for a in case.meta.get("raw_asserts", [])
                        if isinstance(a, dict) and a.get("type") == "llm_judge" and a.get("arg")]
            if criteria:
                judge: dict = {}
                for crit in criteria:
                    judge[crit] = await run_llm_judge(case.input, obs.get("output", ""), crit, judge_llm)
                obs["judge"] = judge
            return obs

        report = await run_eval(cases, run_fn)

        async with SessionLocal() as s:
            run = await s.get(EvalRun, run_id)
            if run is None:
                return
            for r in report.results:
                s.add(EvalCaseResult(
                    run_id=run_id, case_name=r.name, case_passed=r.passed,
                    details=[list(d) for d in r.details], obs=r.obs,
                ))
            run.status = "ok"
            run.score = report.score
            run.passed = report.passed
            run.total = report.total
            run.summary = {"summary": report.summary()}
            run.finished_at = datetime.now(timezone.utc)
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — 실행부 자체 실패는 error 상태로 박제(조용한 running 잔류 금지)
        try:
            async with SessionLocal() as s:
                run = await s.get(EvalRun, run_id)
                if run is not None:
                    run.status = "error"
                    run.error = str(exc)[:1000]
                    run.finished_at = datetime.now(timezone.utc)
                    await s.commit()
        except Exception:
            pass


@router.post("/datasets/{dataset_id}/runs", response_model=RunOut, status_code=202)
async def start_run(
    dataset_id: uuid.UUID,
    body: RunStartIn,
    session: AsyncSession = Depends(get_session),
    user=_run_dep,
) -> RunOut:
    """시험 실행 시작 — EvalRun(running) 즉시 반환, 백그라운드에서 케이스 순차 실행(폴링으로 조회)."""
    ds = await _dataset_or_404(session, dataset_id)
    if ds.kind != "agent":
        raise HTTPException(status_code=400, detail="1탄은 kind=agent 데이터셋만 실행 가능(rag 러너는 후속)")
    agent = await session.get(Agent, body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    n_cases = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset_id))
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
        raise HTTPException(status_code=409, detail="이 문제집은 이미 실행 중입니다 — 완료 후 다시 시도하세요")
    run = EvalRun(
        dataset_id=dataset_id, agent_pk=agent.id, agent_name=agent.name,
        status="running", total=n_cases, owner_id=owner_of(user),
    )
    session.add(run)
    await session.commit()
    asyncio.create_task(_execute_run(run.id, dataset_id, agent.id, user))
    return RunOut.model_validate(run)


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    dataset_id: uuid.UUID | None = None,  # 문제집 필터(스펙 138 — 추이/비교용)
    session: AsyncSession = Depends(get_session), user=_manage
) -> list[RunOut]:
    q = (
        select(EvalRun, EvalDataset.name)
        .join(EvalDataset, EvalDataset.id == EvalRun.dataset_id)
        .order_by(EvalRun.started_at.desc())
        .limit(50)
    )
    if dataset_id is not None:
        q = q.where(EvalRun.dataset_id == dataset_id)
    rows = (await session.execute(q)).all()
    out = []
    for r, ds_name in rows:
        o = RunOut.model_validate(r)
        o.dataset_name = ds_name
        out.append(o)
    return out


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=_manage
) -> RunDetailOut:
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    ds = await session.get(EvalDataset, run.dataset_id)  # 성적표 제목용(codex 137 #4 — 목록만 채우던 것)
    results = (
        await session.execute(
            select(EvalCaseResult).where(EvalCaseResult.run_id == run_id).order_by(EvalCaseResult.created_at)
        )
    ).scalars().all()
    # RunDetailOut을 run으로 직접 model_validate하면 안 된다 — results 필드명이 ORM lazy 관계
    # EvalRun.results와 겹쳐 from_attributes가 비동기 밖 lazy load를 시도, MissingGreenlet 500
    # (129와 같은 부류 — e2e가 포착). RunOut(results 없음)으로 안전 추출 후 명시 구성.
    base = RunOut.model_validate(run)
    return RunDetailOut(
        **base.model_dump(),
        results=[CaseResultOut.model_validate(r) for r in results],
    ).model_copy(update={"dataset_name": ds.name if ds else None})


async def sweep_zombie_runs() -> int:
    """startup 정리(codex 137 #1) — asyncio.create_task는 프로세스 재시작을 못 넘기므로, 부팅 시점에
    남아 있는 status='running'은 전부 죽은 실행이다. error로 박제해 "영원한 실행 중" 잔류를 막는다."""
    async with SessionLocal() as s:
        rows = (
            await s.execute(select(EvalRun).where(EvalRun.status == "running"))
        ).scalars().all()
        for r in rows:
            r.status = "error"
            r.error = "서버 재시작으로 실행이 중단되었습니다 — 다시 실행하세요"
            r.finished_at = datetime.now(timezone.utc)
        if rows:
            await s.commit()
        return len(rows)
