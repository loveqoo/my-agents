"""평가 startup recovery(좀비 스윕) — eval_runs.py에서 분할(스펙 399 P2, 순수 이동).

main lifespan이 eval_routes 경유로 소비 — 재수출 필수(파사드는 eval_runs.py → eval_routes).
"""

from datetime import UTC, datetime

from sqlalchemy import select

from .db import SessionLocal
from .models import EvalDataset, EvalRun


async def sweep_zombie_datasets() -> int:
    """startup 정리(codex 142 계보) — AI 출제(스펙 143) 배경 태스크는 재시작을 못 넘기므로, 부팅
    시점의 "AI 출제 중…" 접미는 전부 죽은 출제다. 중단 박제(영원한 '출제 중' 방지). 컬렉션 통째
    생성("생성 중…" 접두)의 스윕은 스펙 329에서 기능과 함께 제거(라이브 잔여 행 0 실측)."""
    async with SessionLocal() as s:
        rows = (
            (
                await s.execute(
                    select(EvalDataset).where(EvalDataset.description.like("%AI 출제 중…"))
                )
            )
            .scalars()
            .all()
        )
        for dataset in rows:
            dataset.description = (dataset.description or "").replace(
                "AI 출제 중…", "AI 출제 중단(서버 재시작) — 다시 시도하세요"
            )
        if rows:
            await s.commit()
        return len(rows)


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
