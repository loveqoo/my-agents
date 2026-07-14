"""배치 수동 트리거·이력·설정 엔드포인트(admin 보호). 스펙 038.

격리 배치 서비스(`api.batch`)가 자동화 주 경로지만, 브라우저·브랜치에서 같은 작업 함수를 즉시
호출·검증할 수 있게 API에 보호 엔드포인트를 둔다. authz는 admin(*,*)이 ("batch","run")을 이미 커버.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func as safunc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .batch import service as batch_service
from .batch.jobs import JOBS, is_delete_all_pattern
from .batch.runner import run_job
from .db import get_session
from .models import BatchConfig, BatchRun

router = APIRouter(prefix="/admin/batch", tags=["batch"])

_run = Depends(authz.require("batch", "run"))


class BatchConfigOut(BaseModel):
    session_retention_days: int | None
    session_cleanup_cron: str | None
    min_session_turns: int | None
    memory_consolidation_threshold: int | None
    memory_consolidation_cron: str | None
    test_user_email_pattern: str | None
    checkpoint_ttl_hours: int | None
    checkpoint_cleanup_cron: str | None
    token_cleanup_cron: str | None
    approval_retention_days: int | None
    approval_cleanup_cron: str | None
    history_retention_days: int | None
    history_cleanup_cron: str | None


class BatchConfigIn(BaseModel):
    # ge=1: days=0이면 cutoff=now()라 전체 세션이 삭제 대상이 되는 delete-all 푸트건. 1일 미만은 거부(422).
    # NULL은 명시적 비활성으로 허용. jobs.cleanup_sessions에도 days<1 가드가 한 겹 더 있다(방어적).
    session_retention_days: int | None = Field(default=None, ge=1)
    session_cleanup_cron: str | None = None
    # ge=1: 0이면 turns<0 없음이지만 의미상 "모든 세션 미달"로 오인되는 footgun이라 1 미만 거부(422).
    # NULL=비활성. jobs.cleanup_sessions에도 <1 가드가 한 겹 더(learning 037 — 파괴적 노브 바닥).
    min_session_turns: int | None = Field(default=None, ge=1)
    # ge=2: 0/1은 거의 모든 유저를 매번 통합하는 파괴적 churn(learning 037). 2 미만은 거부(422).
    # NULL=비활성. jobs.consolidate_user_memories에도 <2 가드가 한 겹 더 있다(방어적).
    memory_consolidation_threshold: int | None = Field(default=None, ge=2)
    memory_consolidation_cron: str | None = None
    # user-cleanup 대상 이메일 SQL LIKE 패턴. NULL=비활성(명시 설정 전엔 절대 삭제 안 함).
    # 가장 비가역한 노브라 delete-all 가드를 둔다(learning 037 — 파괴적 노브 바닥).
    test_user_email_pattern: str | None = Field(default=None, max_length=200)

    # ge=1: ttl=0이면 방금 만든 체크포인트까지 대상이 되는 delete-all 푸트건(진행 중 턴 파괴).
    # NULL=비활성. checkpoint_retention.sweep에도 <1 가드가 한 겹 더(learning 037 — 파괴적 노브 바닥).
    checkpoint_ttl_hours: int | None = Field(default=None, ge=1)
    checkpoint_cleanup_cron: str | None = None
    token_cleanup_cron: str | None = None
    # ge=1: 0이면 cutoff=now()라 처리된 승인 전량 삭제(delete-all 푸트건). NULL=비활성.
    approval_retention_days: int | None = Field(default=None, ge=1)
    approval_cleanup_cron: str | None = None
    # ge=1: 0이면 전 이력 삭제(delete-all). NULL=비활성.
    history_retention_days: int | None = Field(default=None, ge=1)
    history_cleanup_cron: str | None = None

    @field_validator("test_user_email_pattern")
    @classmethod
    def _reject_delete_all(cls, v: str | None) -> str | None:
        # NULL은 비활성으로 허용. 그 외엔 광범위(전체) 삭제 패턴을 거부 — `%`/빈뿐 아니라 `%@%`·`%a%`처럼
        # 리터럴이 약해 거의 전부를 매치하는 패턴도 막는다(적대리뷰 #1). jobs와 같은 함수를 공유해 드리프트 0.
        if v is None:
            return v
        if not v.strip() or is_delete_all_pattern(v):
            raise ValueError(
                "패턴이 비었거나 너무 광범위합니다 — 도메인을 포함한 구체적 패턴이 필요합니다"
                "(예: verify%@example.com)"
            )
        return v


async def _get_or_create_config(session: AsyncSession) -> BatchConfig:
    cfg = (await session.execute(select(BatchConfig).limit(1))).scalars().first()
    if cfg is None:
        cfg = BatchConfig()
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


@router.get("/jobs", dependencies=[_run])
async def list_jobs() -> dict:
    return {"jobs": sorted(JOBS)}


@router.get("/scheduler", dependencies=[_run])
async def scheduler_status(session: AsyncSession = Depends(get_session)) -> dict:
    """스케줄러 가동 상태(스펙 348) — **안 돌면 화면이 그렇게 말한다**(조용한 무동작 금지).

    `batch_runs`가 0행이었던 이유는 잡이 없어서가 아니라 **cron을 읽어 실행할 프로세스가 없어서**였다.
    그 사실이 어디에도 안 보였다는 게 진짜 결함이라, 상태를 표면화한다.
    """
    st = batch_service.status()
    last = (
        await session.execute(
            select(BatchRun.job_name, safunc.max(BatchRun.started_at))
            .group_by(BatchRun.job_name)
        )
    ).all()
    st["last_runs"] = {j: (t.isoformat() if t else None) for j, t in last}
    return st


@router.post("/{job}/run", dependencies=[_run])
async def trigger(job: str, dry_run: bool = Query(False)) -> dict:
    if job not in JOBS:
        raise HTTPException(status_code=404, detail=f"미지의 작업: {job}")
    return await run_job(job, dry_run=dry_run)


@router.get("/runs", dependencies=[_run])
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        (await session.execute(select(BatchRun).order_by(BatchRun.started_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "job_name": r.job_name,
            "status": r.status,
            "dry_run": r.dry_run,
            "summary": r.summary,
            "error": r.error,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


def _config_out(cfg: BatchConfig) -> BatchConfigOut:
    return BatchConfigOut(
        session_retention_days=cfg.session_retention_days,
        session_cleanup_cron=cfg.session_cleanup_cron,
        min_session_turns=cfg.min_session_turns,
        memory_consolidation_threshold=cfg.memory_consolidation_threshold,
        memory_consolidation_cron=cfg.memory_consolidation_cron,
        test_user_email_pattern=cfg.test_user_email_pattern,
        checkpoint_ttl_hours=cfg.checkpoint_ttl_hours,
        checkpoint_cleanup_cron=cfg.checkpoint_cleanup_cron,
        token_cleanup_cron=cfg.token_cleanup_cron,
        approval_retention_days=cfg.approval_retention_days,
        approval_cleanup_cron=cfg.approval_cleanup_cron,
        history_retention_days=cfg.history_retention_days,
        history_cleanup_cron=cfg.history_cleanup_cron,
    )


@router.get("/config", dependencies=[_run], response_model=BatchConfigOut)
async def get_config(session: AsyncSession = Depends(get_session)) -> BatchConfigOut:
    return _config_out(await _get_or_create_config(session))


@router.patch("/config", dependencies=[_run], response_model=BatchConfigOut)
async def update_config(
    body: BatchConfigIn, session: AsyncSession = Depends(get_session)
) -> BatchConfigOut:
    cfg = await _get_or_create_config(session)
    # PATCH 의미: 보내준 필드만 변경(None도 명시값=비활성). 미전송 필드는 보존.
    data = body.model_dump(exclude_unset=True)
    for field in (
        "session_retention_days",
        "session_cleanup_cron",
        "min_session_turns",
        "memory_consolidation_threshold",
        "memory_consolidation_cron",
        "test_user_email_pattern",
        "checkpoint_ttl_hours",
        "checkpoint_cleanup_cron",
        "token_cleanup_cron",
        "approval_retention_days",
        "approval_cleanup_cron",
        "history_retention_days",
        "history_cleanup_cron",
    ):
        if field in data:
            setattr(cfg, field, data[field])
    await session.commit()
    await session.refresh(cfg)
    # cron 변경을 **즉시** 반영(스펙 348) — 없으면 다음 재시작까지 안 먹는다(조용한 미반영).
    await batch_service.reload_schedules()
    return _config_out(cfg)
