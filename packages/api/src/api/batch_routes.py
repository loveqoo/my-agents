"""배치 수동 트리거·이력·설정 엔드포인트(admin 보호). 스펙 038.

격리 배치 서비스(`api.batch`)가 자동화 주 경로지만, 브라우저·브랜치에서 같은 작업 함수를 즉시
호출·검증할 수 있게 API에 보호 엔드포인트를 둔다. authz는 admin(*,*)이 ("batch","run")을 이미 커버.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .batch.jobs import JOBS
from .batch.runner import run_job
from .db import get_session
from .models import BatchConfig, BatchRun

router = APIRouter(prefix="/admin/batch", tags=["batch"])

_run = Depends(authz.require("batch", "run"))


class BatchConfigOut(BaseModel):
    session_retention_days: int | None
    session_cleanup_cron: str | None


class BatchConfigIn(BaseModel):
    # ge=1: days=0이면 cutoff=now()라 전체 세션이 삭제 대상이 되는 delete-all 푸트건. 1일 미만은 거부(422).
    # NULL은 명시적 비활성으로 허용. jobs.cleanup_sessions에도 days<1 가드가 한 겹 더 있다(방어적).
    session_retention_days: int | None = Field(default=None, ge=1)
    session_cleanup_cron: str | None = None


async def _get_or_create_config(session: AsyncSession) -> BatchConfig:
    cfg = (await session.execute(select(BatchConfig).limit(1))).scalars().first()
    if cfg is None:
        cfg = BatchConfig()
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


@router.get("/jobs", dependencies=[_run])
async def list_jobs():
    return {"jobs": sorted(JOBS)}


@router.post("/{job}/run", dependencies=[_run])
async def trigger(job: str, dry_run: bool = Query(False)):
    if job not in JOBS:
        raise HTTPException(status_code=404, detail=f"미지의 작업: {job}")
    return await run_job(job, dry_run=dry_run)


@router.get("/runs", dependencies=[_run])
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(BatchRun).order_by(BatchRun.started_at.desc()).limit(limit)
        )
    ).scalars().all()
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


@router.get("/config", dependencies=[_run], response_model=BatchConfigOut)
async def get_config(session: AsyncSession = Depends(get_session)):
    cfg = await _get_or_create_config(session)
    return BatchConfigOut(
        session_retention_days=cfg.session_retention_days,
        session_cleanup_cron=cfg.session_cleanup_cron,
    )


@router.patch("/config", dependencies=[_run], response_model=BatchConfigOut)
async def update_config(body: BatchConfigIn, session: AsyncSession = Depends(get_session)):
    cfg = await _get_or_create_config(session)
    # PATCH 의미: 보내준 필드만 변경(None도 명시값=비활성). 미전송 필드는 보존.
    data = body.model_dump(exclude_unset=True)
    if "session_retention_days" in data:
        cfg.session_retention_days = data["session_retention_days"]
    if "session_cleanup_cron" in data:
        cfg.session_cleanup_cron = data["session_cleanup_cron"]
    await session.commit()
    await session.refresh(cfg)
    return BatchConfigOut(
        session_retention_days=cfg.session_retention_days,
        session_cleanup_cron=cfg.session_cleanup_cron,
    )
