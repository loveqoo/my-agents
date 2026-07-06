"""평가 하네스 제품화 라우터 — 문제집/케이스 CRUD + 실행/성적표 (스펙 137·178).

**인가(스펙 178)**: 컬렉션 패턴 = **읽기 공개·관리 소유자**. require("eval",*) admin 게이트를 제거하고
current_principal + ownership.py 술어로 전환 — 멤버가 본인 문제집·본인 쓸 수 있는 에이전트를 자율 평가.
읽기(list/get)는 전 유저 공개(D1), 관리(생성/수정/삭제/실행/출제)는 소유자만(비소유 404-fold). 실행·출제
대상 에이전트는 may_use_agent 게이트(남의 private 평가 차단). asserts는 선언적 JSON →
`eval_harness.build_asserts`가 **닫힌 type 집합**으로 검증(미지 type=400 — 평가는 fail-closed).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_principal
from .db import get_session
from .eval_harness import build_asserts
from .models import EvalCase, EvalDataset
from .ownership import assert_may_manage, is_privileged, may_manage, may_use_agent, owner_of

router = APIRouter(prefix="/eval", tags=["eval"])

# 스펙 178: 평가는 소유 기반(컬렉션 패턴 = 읽기 공개·관리 소유자). require("eval",*) admin 게이트를
# 제거하고 current_principal + ownership.py 술어로 전환 — 멤버가 본인 문제집·본인 쓸 수 있는 에이전트를
# 자율 평가. 읽기(list/get)는 전 유저 공개(D1), 관리(생성/수정/삭제/실행)는 소유자만(비소유 404-fold).


# ----------------------------- 스키마 -----------------------------
class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    kind: str = Field(default="agent", pattern="^(agent|rag)$")
    collection_id: uuid.UUID | None = None  # 스펙 193 — kind=rag면 대상 컬렉션 고정(생성 시 저장)


class DatasetOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    kind: str
    collection_id: uuid.UUID | None = None  # 스펙 193 — RAG 문제집의 고정 컬렉션(실행 시 재선택 불필요)
    case_count: int = 0
    can_manage: bool = True  # 스펙 178 — 이 유저가 수정/삭제/실행 가능(소유자·특권). UI 버튼 게이트
    generating: bool = False  # 스펙 193 — 문제 자동 생성 진행 중(목록 스피너·드로어 Skeleton·폴링 신호)


def _dataset_out(d: EvalDataset, case_count: int, user) -> DatasetOut:
    """DatasetOut 단일 생성 경로(드리프트 0) — 5곳 인라인 통일. generating은 description 진행 마커를
    구조 필드로 승격(프론트는 bool만 소비 → 목록 배지·드로어 Skeleton·폴링).
    두 경로: 컬렉션 생성(142)="생성 중…"(접두), AI 출제(143/195)="… · AI 출제 중…"(접미). 둘 다 봐야
    출제 시에도 Skeleton이 뜬다(스펙 195 후속 — 접두만 보던 버그)."""
    desc = d.description or ""
    return DatasetOut(
        id=d.id, name=d.name, description=d.description, kind=d.kind,
        collection_id=d.collection_id, case_count=case_count,
        can_manage=may_manage(d.owner_id, user),
        generating=desc.startswith("생성 중") or desc.endswith("AI 출제 중…"),
    )


class CaseIn(BaseModel):
    # 스펙 195: 이름은 UI서 제거 — 없으면 서버가 해시(case-xxxxxxxx) 생성(유저 비노출·내부 관리).
    # 성적표엔 질문(input)이 뜨므로 유저는 이름을 볼 일이 없다. update 시 미전송이면 기존 보존.
    name: str | None = Field(default=None, max_length=200)
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
    session: AsyncSession = Depends(get_session), user=Depends(current_principal)
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
        _dataset_out(d, n, user)  # 읽기는 전원, 관리 버튼은 소유자만(헬퍼가 collection_id·generating 포함)
        for d, n in rows
    ]


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def create_dataset(
    body: DatasetIn, session: AsyncSession = Depends(get_session), user=Depends(current_principal)
) -> DatasetOut:
    ds = EvalDataset(
        name=body.name, description=body.description, kind=body.kind, owner_id=owner_of(user),
        # 스펙 193: rag 문제집만 대상 컬렉션 고정(agent는 무의미 → None으로 무시).
        collection_id=body.collection_id if body.kind == "rag" else None,
    )
    session.add(ds)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 문제집이 이미 있습니다")
    return _dataset_out(ds, 0, user)


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    dataset_id: uuid.UUID,
    body: DatasetIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_principal),
) -> DatasetOut:
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 소유자만(비소유 404-fold)
    ds.name, ds.description, ds.kind = body.name, body.description, body.kind
    await session.commit()
    n = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id))
    ).scalar_one()
    return _dataset_out(ds, n, user)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=Depends(current_principal)
) -> None:
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 소유자만(비소유 404-fold)
    await session.delete(ds)  # cases·runs CASCADE
    await session.commit()


# ----------------------------- 케이스 CRUD -----------------------------
@router.get("/datasets/{dataset_id}/cases", response_model=list[CaseOut])
async def list_cases(
    dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=Depends(current_principal)
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
    user=Depends(current_principal),
) -> CaseOut:
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 문제집 소유자만 케이스 추가
    _validate_asserts(body.asserts)
    import secrets
    case = EvalCase(
        dataset_id=dataset_id, name=body.name or f"case-{secrets.token_hex(4)}",  # 스펙 195: 없으면 해시
        input=body.input, asserts=body.asserts, order_idx=body.order_idx,
    )
    session.add(case)
    await session.commit()
    return CaseOut.model_validate(case)


@router.patch("/cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID, body: CaseIn, session: AsyncSession = Depends(get_session), user=Depends(current_principal)
) -> CaseOut:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    ds = await session.get(EvalDataset, case.dataset_id)  # 케이스는 owner 없음 — 부모 문제집으로 판정
    if ds is None:
        raise HTTPException(status_code=404, detail="case not found")
    assert_may_manage(ds, user, not_found_detail="case not found")  # 소유자만(비소유 404-fold)
    _validate_asserts(body.asserts)
    if body.name is not None:  # 스펙 195: 미전송이면 기존 해시 이름 보존(덮어쓰기 금지)
        case.name = body.name
    case.input, case.asserts, case.order_idx = body.input, body.asserts, body.order_idx
    await session.commit()
    return CaseOut.model_validate(case)


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=Depends(current_principal)
) -> None:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    ds = await session.get(EvalDataset, case.dataset_id)  # 부모 문제집으로 소유 판정
    if ds is None:
        raise HTTPException(status_code=404, detail="case not found")
    assert_may_manage(ds, user, not_found_detail="case not found")  # 소유자만(비소유 404-fold)
    await session.delete(case)
    await session.commit()


# ----------------------------- 실행/성적표 (단계 ②) -----------------------------
import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from .db import SessionLocal  # noqa: E402
from .eval_harness import EvalCase as HarnessCase, run_eval  # noqa: E402
from .eval_runner import eval_run_agent  # noqa: E402
from .models import Agent, EvalCaseResult, EvalRun  # noqa: E402

# 스펙 178 비용 가드 — 비특권(멤버) 자율 실행이 실모델을 폭주시키지 않게. 특권(admin)은 무제한.
_MEMBER_MAX_CONCURRENT_RUNS = 2  # 유저당 동시 running run 상한(전 문제집 합산)
_MEMBER_MAX_RUN_WORK = 60  # 1회 실행 LLM 호출 상한 = models × (cases + llm_judge 기준 수)(codex 178)
_MEMBER_MAX_CONCURRENT_JOBS = 2  # 유저당 동시 배경 LLM 작업(생성/출제) 상한(codex 178: generate/suggest flood 차단)


async def _member_run_guard(session: AsyncSession, user, dataset_id: uuid.UUID, n_models: int) -> None:
    """비특권 실행 비용 가드(스펙 178, codex 반영). 특권은 호출 전 단락. per-user advisory 락으로
    동시성 확인+삽입 사이 TOCTOU를 직렬화(codex #3), work는 judge 호출까지 포함(codex #5)."""
    owner = owner_of(user)
    # per-user 직렬화 — 병렬 요청이 my_running<2를 동시에 보고 상한을 넘기는 race 차단. xact 종료 시 해제.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"eval-run:{owner}"})
    my_running = (
        await session.execute(
            select(func.count(EvalRun.id)).where(EvalRun.owner_id == owner, EvalRun.status == "running")
        )
    ).scalar_one()
    if my_running >= _MEMBER_MAX_CONCURRENT_RUNS:
        raise HTTPException(
            status_code=429,
            detail=f"동시 실행 한도({_MEMBER_MAX_CONCURRENT_RUNS})에 도달했습니다 — 진행 중 실행이 끝나면 다시 시도하세요",
        )
    # work = 실 LLM 호출량 ≈ models × (케이스 + 케이스별 llm_judge 기준 수). judge 누락 보정(codex #5).
    asserts_rows = (
        await session.execute(select(EvalCase.asserts).where(EvalCase.dataset_id == dataset_id))
    ).scalars().all()
    n_cases = len(asserts_rows)
    judge_count = sum(
        1 for row in asserts_rows for a in (row or [])
        if isinstance(a, dict) and a.get("type") == "llm_judge"
    )
    work = max(1, n_models) * (n_cases + judge_count)
    if work > _MEMBER_MAX_RUN_WORK:
        raise HTTPException(
            status_code=422,
            detail=f"실행 규모(모델 {max(1, n_models)} × [케이스 {n_cases} + 판정 {judge_count}] = {work})가 한도 {_MEMBER_MAX_RUN_WORK}를 넘습니다 — 케이스·판정·모델 수를 줄이세요",
        )


async def _member_job_guard(session: AsyncSession, user, exclude_id: uuid.UUID | None = None) -> None:
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


class RunStartIn(BaseModel):
    agent_id: uuid.UUID | None = None  # kind=agent: agents.id (pk)
    collection_id: uuid.UUID | None = None  # kind=rag: 컬렉션 id (스펙 140)
    models: list[str] = Field(default_factory=list, max_length=6)  # 모델 비교(스펙 141, agent 전용)


class RunOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None  # 목록 표시용(조인 채움)
    agent_name: str | None
    model_name: str | None = None  # 모델 오버라이드 박제(스펙 141)
    group_id: uuid.UUID | None = None  # 모델 비교 그룹(스펙 141)
    status: str
    score: float | None
    passed: int
    total: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    can_manage: bool = True  # 스펙 178 — 이 유저가 이 실행(성적표)을 관리 가능(소유자·특권)
    model_config = {"from_attributes": True}


class CaseResultOut(BaseModel):
    case_name: str
    case_passed: bool
    details: list
    obs: dict | None
    model_config = {"from_attributes": True}


class RunDetailOut(RunOut):
    results: list[CaseResultOut] = []


async def _execute_run(run_id: uuid.UUID, dataset_id: uuid.UUID, agent_pk, principal,
                       rag_collection: dict | None = None, overrides: dict | None = None) -> None:
    """백그라운드 실행(batch runner 미러) — 케이스 **순차**(실모델 rate-limit·격리), 상태머신
    running→ok|error. kind=rag면 rag_collection으로 검색 러너(스펙 140), 아니면 agent 러너.
    케이스/러너 실패는 하네스가 error 관측으로 접어 전체는 계속(조용한 초록 금지)."""
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
                # 스펙 195: 성적표 식별자(case_name)에 **질문**을 넣는다 — DB name은 내부 해시라
                # 성적표에 뜨면 유저가 못 알아본다. 표시 상한 200자.
                HarnessCase(name=(c.input or c.name)[:200], input=c.input, asserts=build_asserts(c.asserts),
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
            if rag_collection is not None:
                from .eval_runner import eval_run_rag
                obs = await eval_run_rag(rag_collection, case.input)
            else:
                obs = await eval_run_agent(agent_pk, case.input, principal, overrides)
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


async def _execute_group(specs: list[tuple], dataset_id: uuid.UUID, agent_pk, principal) -> None:
    """모델 비교 그룹 실행(스펙 141) — (run_id, model_name)들을 **순차**로(로컬 LLM 과점유 방지).
    개별 런 실패는 _execute_run이 error로 박제하고 다음 모델은 계속."""
    for run_id, model_name in specs:
        await _execute_run(run_id, dataset_id, agent_pk, principal,
                           overrides={"model": model_name} if model_name else None)


@router.post("/datasets/{dataset_id}/runs", response_model=RunOut, status_code=202)
async def start_run(
    dataset_id: uuid.UUID,
    body: RunStartIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_principal),
) -> RunOut:
    """시험 실행 시작 — EvalRun(running) 즉시 반환, 백그라운드에서 케이스 순차 실행(폴링으로 조회)."""
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 본인 문제집만 실행(비소유 404-fold)
    # kind별 대상 해석(스펙 140): agent 시험=agent_id, rag 시험=collection_id.
    agent = None
    rag_collection = None
    target_name = None
    if body.agent_id is not None and body.collection_id is not None:
        # 교차 대상 거부(codex 140 #1) — 조용한 무시는 "다른 대상을 시험했다"는 오해를 만든다.
        raise HTTPException(status_code=400, detail="agent_id와 collection_id는 동시에 줄 수 없습니다")
    if ds.kind == "rag":
        # 스펙 193: 문제집에 고정된 컬렉션 우선. body 값은 하위호환·구버전 첫 실행(lazy 고정)용.
        coll_id = ds.collection_id or body.collection_id
        if coll_id is None:
            raise HTTPException(status_code=400, detail="RAG 문제집은 collection_id가 필요합니다")
        from .rag import resolve_search_collection
        rag_collection = await resolve_search_collection(session, coll_id)  # 404/400 자체 처리
        target_name = f"RAG · {rag_collection['name']}"
        if ds.collection_id is None:  # 구버전 문제집: 첫 실행 때 고른 컬렉션을 고정(이후 재선택 불필요)
            ds.collection_id = coll_id
    else:
        if body.agent_id is None:
            raise HTTPException(status_code=400, detail="에이전트 문제집은 agent_id가 필요합니다")
        agent = await session.get(Agent, body.agent_id)
        # 스펙 178 구멍#1 봉합: 쓸 수 있는 에이전트만 평가 대상(남의 private을 UUID로 지정해도 404-fold).
        if agent is None or not may_use_agent(agent, user):
            raise HTTPException(status_code=404, detail="agent not found")
        target_name = agent.name
    if dataset_id in _active_jobs or (ds.description or "").startswith("생성 중"):
        # 골든 생성/출제 진행 중 실행 금지(codex 142/143) — 락 우선, description은 재시작 잔류용 보조.
        raise HTTPException(status_code=409, detail="문제 생성이 진행 중입니다 — 완료 후 실행하세요")
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
    # 모델 비교(스펙 141) — kind=agent 전용. 이름은 레지스트리 chat 모델로 **사전 검증**:
    # _load_context는 미존재 이름을 기본 모델로 만회하므로(설정 만회 함정 — 스펙 089와 동류)
    # 여기서 안 막으면 "다른 모델로 조용히 시험"이 된다.
    models: list[str] = [m.strip() for m in body.models if m and m.strip()]
    if models:
        if ds.kind != "agent":
            raise HTTPException(status_code=400, detail="모델 비교는 에이전트 문제집에서만 가능합니다")
        if len(set(models)) != len(models):
            raise HTTPException(status_code=400, detail="모델 이름이 중복되었습니다")
        from .models import ModelConfig
        rows = (
            await session.execute(
                select(ModelConfig.name).where(
                    ModelConfig.kind == "chat", ModelConfig.name.in_(models)
                )
            )
        ).scalars().all()
        missing = sorted(set(models) - set(rows))
        if missing:
            raise HTTPException(status_code=400, detail=f"레지스트리에 없는 chat 모델: {', '.join(missing)}")

    # 스펙 178 비용 가드(비특권 자율 실행) — 특권은 무제한. advisory 락+judge 포함 work(codex 반영).
    if not is_privileged(user):
        await _member_run_guard(session, user, dataset_id, len(models))

    if len(models) == 1:
        # 1개 선택=비교가 아니라 단순 모델 오버라이드 런(codex 141 #3 — 1열 그룹은 격자 의미 없음).
        run = EvalRun(dataset_id=dataset_id, agent_pk=agent.id, agent_name=target_name,
                      model_name=models[0], status="running", total=n_cases, owner_id=owner_of(user))
        session.add(run)
        await session.commit()
        asyncio.create_task(_execute_run(run.id, dataset_id, agent.id, user,
                                         overrides={"model": models[0]}))
        return RunOut.model_validate(run)

    if models:
        group_id = uuid.uuid4()
        runs = [
            EvalRun(dataset_id=dataset_id, agent_pk=agent.id, agent_name=target_name,
                    model_name=m, group_id=group_id, status="running", total=n_cases,
                    owner_id=owner_of(user))
            for m in models
        ]
        session.add_all(runs)
        await session.commit()
        asyncio.create_task(_execute_group([(r.id, r.model_name) for r in runs],
                                           dataset_id, agent.id, user))
        return RunOut.model_validate(runs[0])

    run = EvalRun(
        dataset_id=dataset_id, agent_pk=agent.id if agent else None, agent_name=target_name,
        status="running", total=n_cases, owner_id=owner_of(user),
    )
    session.add(run)
    await session.commit()
    asyncio.create_task(_execute_run(run.id, dataset_id, agent.id if agent else None, user,
                                     rag_collection=rag_collection))
    return RunOut.model_validate(run)


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    dataset_id: uuid.UUID | None = None,  # 문제집 필터(스펙 138 — 추이/비교용)
    group_id: uuid.UUID | None = None,  # 비교 그룹 전량 조회(스펙 141 — 최근 50 컷에 그룹이 잘리면 부분 격자, codex #1)
    session: AsyncSession = Depends(get_session), user=Depends(current_principal)
) -> list[RunOut]:
    q = (
        select(EvalRun, EvalDataset.name)
        .join(EvalDataset, EvalDataset.id == EvalRun.dataset_id)
        .order_by(EvalRun.started_at.desc())
    )
    if group_id is not None:
        q = q.where(EvalRun.group_id == group_id)  # 그룹은 최대 6건 — limit 불요
    else:
        q = q.limit(50)
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
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session), user=Depends(current_principal)
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
    ).model_copy(update={"dataset_name": ds.name if ds else None,
                         "can_manage": may_manage(run.owner_id, user)})


async def sweep_zombie_datasets() -> int:
    """startup 정리(codex 142) — 생성 백그라운드 태스크는 재시작을 못 넘기므로, 부팅 시점의
    "생성 중…" description은 전부 죽은 생성이다. 정직 박제(영원한 '생성 중' 방지)."""
    async with SessionLocal() as s:
        rows = (
            await s.execute(select(EvalDataset).where(EvalDataset.description.like("생성 중%")))
        ).scalars().all()
        for d in rows:
            d.description = "생성 중단(서버 재시작) — 삭제 후 다시 생성하세요"
        # AI 출제(스펙 143)도 같은 create_task라 재시작에 죽는다 — 접미 상태를 중단 박제.
        rows2 = (
            await s.execute(select(EvalDataset).where(EvalDataset.description.like("%AI 출제 중…")))
        ).scalars().all()
        for d in rows2:
            d.description = (d.description or "").replace("AI 출제 중…", "AI 출제 중단(서버 재시작) — 다시 시도하세요")
        if rows or rows2:
            await s.commit()
        return len(rows) + len(rows2)


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


# ----------------------------- 골든셋 자동 생성 (스펙 142) -----------------------------
class GenerateIn(BaseModel):
    collection_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    count: int = Field(default=10, ge=1, le=20)


async def _execute_generation(dataset_id: uuid.UUID, collection_id: uuid.UUID, count: int) -> None:
    """백그라운드 골든 생성 — 완료/실패를 dataset.description에 박제(조용한 빈 문제집 금지).
    케이스 기준은 자기일관 골든 3종: 출처 문서 회수 + 결과 존재 + 오류 없음."""
    from .eval_golden import generate_golden_cases

    _active_jobs.add(dataset_id)
    try:
        from . import crypto
        from .mem_config import _default_chat_model

        async with SessionLocal() as s:
            cm = await _default_chat_model(s)
        if cm is None or cm.provider is None or not cm.provider.base_url or not cm.model_id:
            raise RuntimeError("기본 chat 모델 미설정 — 질문 생성 불가")
        llm_cfg = {"base_url": cm.provider.base_url,
                   "api_key": crypto.decrypt(cm.provider.api_key), "model_id": cm.model_id}
        result = await generate_golden_cases(collection_id, count, llm_cfg)
        async with SessionLocal() as s:
            ds = await s.get(EvalDataset, dataset_id)
            if ds is None:
                return
            for i, c in enumerate(result["cases"]):
                s.add(EvalCase(
                    dataset_id=dataset_id, name=f"골든 {i + 1} · {c['filename'][:60]}",
                    input=c["question"], order_idx=i,
                    asserts=[
                        {"type": "rag_source_contains", "arg": c["filename"][:500]},
                        {"type": "rag_hits_gte", "arg": "1"},
                        {"type": "no_error"},
                    ],
                ))
            made = len(result["cases"])
            if made == 0:
                # 조용한 빈 문제집 금지(codex 142) — 0건은 성공이 아니라 실패다.
                ds.description = (
                    f"생성 실패: 케이스 0건 (요청 {count}, 건너뜀 {result['skipped']}) — "
                    "컬렉션 문서가 너무 짧거나 생성 모델 응답이 형식을 벗어났습니다. 삭제 후 다시 시도하세요"
                )
            else:
                ds.description = (
                    f"자동 생성 {made}건 (요청 {count}"
                    + (f", 건너뜀 {result['skipped']}" if result["skipped"] else "")
                    + ") — 문제는 열어서 검토·수정하세요"
                )
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — 실패도 description에 정직 박제
        try:
            async with SessionLocal() as s:
                ds = await s.get(EvalDataset, dataset_id)
                if ds is not None:
                    ds.description = f"생성 실패: {str(exc)[:200]} — 삭제 후 다시 시도하세요"
                    await s.commit()
        except Exception:
            pass
    finally:
        _active_jobs.discard(dataset_id)


@router.post("/generate-dataset", response_model=DatasetOut, status_code=202)
async def generate_dataset(
    body: GenerateIn, session: AsyncSession = Depends(get_session), user=Depends(current_principal)
) -> DatasetOut:
    """컬렉션에서 RAG 문제집 자동 생성(스펙 142) — 문제집 즉시 반환, 케이스는 백그라운드 생성
    (완료/실패는 description으로 확인). 컬렉션 완전성은 검색 해석기로 사전 검증."""
    from .rag import resolve_search_collection

    await resolve_search_collection(session, body.collection_id)  # 404/400 사전 검증
    # 스펙 178 비용 가드 — 비특권 유저의 배경 생성 flood 차단(codex #1). 특권 무제한.
    if not is_privileged(user):
        await _member_job_guard(session, user)  # 생성 전 기존 in-flight만 카운트
    ds = EvalDataset(name=body.name, description="생성 중… (문제가 곧 채워집니다)",
                     kind="rag", owner_id=owner_of(user),
                     collection_id=body.collection_id)  # 스펙 193: 생성 컬렉션을 문제집에 고정
    session.add(ds)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 문제집이 이미 있습니다")
    _active_jobs.add(ds.id)  # 동기 등록 — create_task 전 창을 닫아 flood 카운트 누락 방지(codex #1)
    asyncio.create_task(_execute_generation(ds.id, body.collection_id, body.count))
    return _dataset_out(ds, 0, user)


# ----------------------------- AI 출제 (스펙 143 — 평가 도우미 1탄) -----------------------------
# 진행 중 백그라운드 작업 락(codex 143 — description 접미 검사는 PATCH로 우회/오작동 가능).
# create_task와 수명이 같아 재시작 시 자동 소멸(잔류 description은 sweep이 정리).
_active_jobs: set = set()


class SuggestIn(BaseModel):
    agent_id: uuid.UUID | None = None  # 스펙 195: rag 문제집은 불필요(고정 컬렉션 사용)
    count: int = Field(default=10, ge=1, le=10)


class HelperStatusOut(BaseModel):
    available: bool
    reason: str | None = None


async def _helper_llm(session: AsyncSession) -> tuple[dict | None, str | None]:
    """도우미 LLM 해석 — (llm_cfg, 불가 사유). 기본 chat이 실모델일 때만(사용자 원칙)."""
    from . import crypto
    from .eval_suggest import is_mock_llm
    from .mem_config import _default_chat_model

    cm = await _default_chat_model(session)
    if cm is None or cm.provider is None or not cm.provider.base_url or not cm.model_id:
        return None, "기본 chat 모델이 없습니다 — 프로바이더·모델에서 기본 모델을 지정하세요"
    if is_mock_llm(cm.provider.base_url, cm.model_id):
        return None, "기본 chat 모델이 mock입니다 — 실모델을 기본으로 지정하면 도우미가 활성화됩니다"
    return {
        "base_url": cm.provider.base_url,
        "api_key": crypto.decrypt(cm.provider.api_key),
        "model_id": cm.model_id,
    }, None


@router.get("/helper-status", response_model=HelperStatusOut)
async def helper_status(
    session: AsyncSession = Depends(get_session), user=Depends(current_principal)
) -> HelperStatusOut:
    """도우미 가용성 — UI가 버튼 활성/비활성+사유 툴팁에 사용(정직 비활성)."""
    _llm, reason = await _helper_llm(session)
    return HelperStatusOut(available=_llm is not None, reason=reason)


async def _execute_suggestion(dataset_id: uuid.UUID, agent_pk: uuid.UUID, count: int,
                              llm_cfg: dict, prior_desc: str | None) -> None:
    """백그라운드 출제 — 기존 문제 보존(추가만), description에 상태 박제(142 패턴).
    order_idx는 기존 최대값 뒤로 이어붙인다. 게이트는 _active_jobs(메모리 락)."""
    from .eval_suggest import suggest_agent_cases

    # 락(_active_jobs)은 엔드포인트가 동기 획득(codex #2). 여기선 완료 시 finally에서 해제만.
    try:
        result = await suggest_agent_cases(agent_pk, count, llm_cfg)
        async with SessionLocal() as s:
            ds = await s.get(EvalDataset, dataset_id)
            if ds is None:
                return
            base_idx = (
                await s.execute(
                    select(func.coalesce(func.max(EvalCase.order_idx), -1)).where(
                        EvalCase.dataset_id == dataset_id
                    )
                )
            ).scalar_one() + 1
            for i, c in enumerate(result["cases"]):
                s.add(EvalCase(
                    dataset_id=dataset_id,
                    name=f"AI 출제 {base_idx + i + 1} ({'RAG' if c['label'] == 'rag' else '역할'})",
                    input=c["question"], order_idx=base_idx + i, asserts=c["asserts"],
                ))
            made = len(result["cases"])
            tail = (
                f"AI 출제 {made}건 추가 (요청 {count}"
                + (f", 건너뜀 {result['skipped']}" if result["skipped"] else "") + ")"
                if made else f"AI 출제 실패: 0건 (요청 {count}, 건너뜀 {result['skipped']})"
            )
            # 완료 표기는 **현재** description 기준(codex 143 — 진행 중 사용자 편집 보존):
            # "AI 출제 중…" 접미가 남아 있으면 치환, 사용자가 바꿨으면 그 값 뒤에 덧붙인다.
            cur = ds.description or ""
            if cur.endswith("AI 출제 중…"):
                ds.description = cur[: -len("AI 출제 중…")].rstrip(" ·") or None
                ds.description = f"{ds.description} · {tail}" if ds.description else tail
            else:
                ds.description = f"{cur} · {tail}" if cur else tail
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — 실패도 정직 박제
        try:
            async with SessionLocal() as s:
                ds = await s.get(EvalDataset, dataset_id)
                if ds is not None:
                    ds.description = f"{prior_desc + ' · ' if prior_desc else ''}AI 출제 실패: {str(exc)[:150]}"
                    await s.commit()
        except Exception:
            pass
    finally:
        _active_jobs.discard(dataset_id)


async def _execute_generation_append(dataset_id: uuid.UUID, collection_id: uuid.UUID, count: int,
                                     llm_cfg: dict, prior_desc: str | None) -> None:
    """RAG 문제집 AI 출제(스펙 195) — 골든 생성을 **기존 문제집에 추가**(order_idx 이어붙임).
    generate_dataset(신규 문제집)과 달리 append + suggest 패턴 description(기존 보존). name은 해시
    (스펙 195 — 유저 비노출, 성적표엔 input이 뜬다). 락 해제는 finally."""
    from .eval_golden import generate_golden_cases
    import secrets

    try:
        result = await generate_golden_cases(collection_id, count, llm_cfg)
        async with SessionLocal() as s:
            ds = await s.get(EvalDataset, dataset_id)
            if ds is None:
                return
            base_idx = (
                await s.execute(
                    select(func.coalesce(func.max(EvalCase.order_idx), -1)).where(
                        EvalCase.dataset_id == dataset_id
                    )
                )
            ).scalar_one() + 1
            for i, c in enumerate(result["cases"]):
                s.add(EvalCase(
                    dataset_id=dataset_id, name=f"case-{secrets.token_hex(4)}",
                    input=c["question"], order_idx=base_idx + i,
                    asserts=[
                        {"type": "rag_source_contains", "arg": c["filename"][:500]},
                        {"type": "rag_hits_gte", "arg": "1"},
                        {"type": "no_error"},
                    ],
                ))
            made = len(result["cases"])
            tail = (
                f"AI 출제 {made}건 추가 (요청 {count}"
                + (f", 건너뜀 {result['skipped']}" if result["skipped"] else "") + ")"
                if made else f"AI 출제 실패: 0건 (요청 {count}, 건너뜀 {result['skipped']})"
            )
            cur = ds.description or ""
            if cur.endswith("AI 출제 중…"):
                ds.description = cur[: -len("AI 출제 중…")].rstrip(" ·") or None
                ds.description = f"{ds.description} · {tail}" if ds.description else tail
            else:
                ds.description = f"{cur} · {tail}" if cur else tail
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — 실패도 정직 박제
        try:
            async with SessionLocal() as s:
                ds = await s.get(EvalDataset, dataset_id)
                if ds is not None:
                    ds.description = f"{prior_desc + ' · ' if prior_desc else ''}AI 출제 실패: {str(exc)[:150]}"
                    await s.commit()
        except Exception:
            pass
    finally:
        _active_jobs.discard(dataset_id)


@router.post("/datasets/{dataset_id}/suggest-cases", response_model=DatasetOut, status_code=202)
async def suggest_cases(
    dataset_id: uuid.UUID,
    body: SuggestIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_principal),
) -> DatasetOut:
    """문제집 AI 출제 — 기존 문제 보존+추가, 백그라운드(상태=description). agent=에이전트 구성 기반(143),
    rag=고정 컬렉션 골든 생성 append(195). 둘 다 소유자만·비용가드·도우미 실모델 필요."""
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(ds, user, not_found_detail="dataset not found")  # 소유자만 출제(비소유 404-fold)
    if ds.kind == "rag" and ds.collection_id is None:  # 스펙 195: rag는 고정 컬렉션 필요
        raise HTTPException(status_code=400, detail="이 RAG 문제집에 고정된 컬렉션이 없습니다 — 먼저 시험 실행으로 컬렉션을 고정하세요")
    if dataset_id in _active_jobs:
        raise HTTPException(status_code=409, detail="이미 출제가 진행 중입니다")
    _active_jobs.add(dataset_id)  # 동기 락 — 배경 태스크로 미루면 중복 출제 TOCTOU(codex #2). check와 사이에 await 없음.
    try:
        agent_pk = None
        if ds.kind == "agent":  # 스펙 178 구멍#1: 쓸 수 있는 에이전트만 출제 대상(남의 private 미노출).
            agent = await session.get(Agent, body.agent_id) if body.agent_id else None
            if agent is None or not may_use_agent(agent, user):
                raise HTTPException(status_code=404, detail="agent not found")
            agent_pk = agent.id
        # 스펙 178 비용 가드 — 비특권 배경 작업 동시 상한(codex #1·#2). 현재 락은 제외 카운트.
        if not is_privileged(user):
            await _member_job_guard(session, user, exclude_id=dataset_id)
        llm_cfg, reason = await _helper_llm(session)
        if llm_cfg is None:
            raise HTTPException(status_code=400, detail=f"도우미 사용 불가: {reason}")
        prior = ds.description
        ds.description = f"{prior + ' · ' if prior else ''}AI 출제 중…"
        await session.commit()
        if ds.kind == "rag":  # 스펙 195: 고정 컬렉션 골든을 기존 문제집에 append
            asyncio.create_task(_execute_generation_append(dataset_id, ds.collection_id, body.count, llm_cfg, prior))
        else:
            asyncio.create_task(_execute_suggestion(dataset_id, agent_pk, body.count, llm_cfg, prior))
    except Exception:
        _active_jobs.discard(dataset_id)  # create_task까지 못 가면 배경 finally가 안 돌아 락이 샌다
        raise
    n = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id))
    ).scalar_one()
    return _dataset_out(ds, n, user)
