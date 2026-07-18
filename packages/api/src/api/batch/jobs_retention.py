"""보존기간 회수 잡 5종 — jobs.py에서 분할(스펙 395 P3, 순수 이동).

cleanup_tokens(349)·cleanup_approvals(350)·cleanup_history(351)·cleanup_checkpoints(346 위임)·
cleanup_memories(352 위임 — mem0 orphan은 판정=삭제 단일 SQL의 TOCTOU 계약이라 내부는
memory.reclaim에 격리, 여기는 wrapper만). 파사드는 jobs.py(재수출 계약).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy import func as safunc

from .. import checkpoint_retention
from ..db import SessionLocal
from ..memory import reclaim
from ..models import AccessToken, Approval, BatchRun, EvalRun, MemorySnapshot
from .jobs_shared import _get_config

log = logging.getLogger("api.batch.jobs")


async def cleanup_checkpoints(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — runner가 키워드 호출(계약)
    """체크포인트 스윕(스펙 346) — 관문을 못 탄 고아 + 방치된 승인 대기를 회수.

    정상 경로는 턴 종료 관문(`checkpoint_retention.release_thread`)이 덮는다. 이 잡은 **프로세스가
    죽은 턴**이 남긴 고아를 나이(TTL)로 회수하고, TTL을 넘긴 pending 승인은 `expired`로 만료 표시한 뒤
    스레드를 지운다(조용한 삭제 금지 — 회고 038).

    TTL은 BatchConfig.checkpoint_ttl_hours. NULL/<1이면 비활성(파괴적 노브 바닥, learning 037).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        ttl = cfg.checkpoint_ttl_hours
        await session.commit()
    return await checkpoint_retention.sweep(dry_run=dry_run, ttl_hours=ttl)


# 만료 토큰 회수의 유예(스펙 349) — 만료 직후 경계에서 지우지 않는다(시계 오차·진행 중 요청 보호).
_TOKEN_GRACE = timedelta(days=1)


async def cleanup_tokens(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — runner가 키워드 호출(계약)
    """만료된 세션 토큰 회수(스펙 349) — 로그인마다 1행 쌓이는데 지우는 코드가 로그아웃뿐이었다.

    `fastapi_users`의 DatabaseStrategy는 읽을 때 `created_at >= max_age`로 **거를 뿐** 지우지 않는다.
    즉 만료된 토큰(인증에 못 쓰는 자격증명 조각)이 DB에 영원히 남는다 — 위생·보안 부채.

    **살아 있는 토큰은 절대 안 지운다**(로그인 상태를 끊는 건 파괴적 부작용). 수명은 인증과 **같은
    출처**(`users.SESSION_LIFETIME_SECONDS`)를 읽는다 — 상수를 두 곳에 두면 한쪽만 바뀐다(드리프트).

    파괴적 노브엔 바닥(learning 037): 수명이 비정상(<=0)이면 **잡을 비활성**한다 — 0을 "전부 만료"로
    매핑하면 전 사용자 로그아웃이라는 delete-all이 된다.
    """
    from ..users import SESSION_LIFETIME_SECONDS

    if SESSION_LIFETIME_SECONDS <= 0:
        # 수명이 0/음수면 "모든 토큰이 만료"로 해석돼 전량 삭제가 된다 — 바닥을 깐다.
        return {"status": "disabled", "reason": "SESSION_LIFETIME_SECONDS<=0", "deleted": 0}

    cutoff = datetime.now(UTC) - timedelta(seconds=SESSION_LIFETIME_SECONDS) - _TOKEN_GRACE
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AccessToken.created_at).where(AccessToken.created_at < cutoff)
            )
        ).all()
        n = len(rows)
        if dry_run:
            return {
                "status": "dry_run",
                "cutoff": cutoff.isoformat(),
                "lifetime_seconds": SESSION_LIFETIME_SECONDS,
                "would_delete": n,
            }
        if n:
            await session.execute(delete(AccessToken).where(AccessToken.created_at < cutoff))
            await session.commit()
    log.info("만료 토큰 정리: %d행 삭제(기준 %s)", n, cutoff.isoformat())
    return {
        "status": "ok",
        "cutoff": cutoff.isoformat(),
        "lifetime_seconds": SESSION_LIFETIME_SECONDS,
        "deleted": n,
    }


async def cleanup_approvals(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — runner가 키워드 호출(계약)
    """처리된 승인 회수(스펙 350) — 위험 도구 호출마다 1행 쌓이는데 삭제 코드가 리포 전체에 없었다.

    **pending은 절대 안 지운다** — 그건 **재개의 근거**다(회고 038: pending approval을 지우면 그래프가
    재개 불가 고아가 된다). 방치된 pending은 스펙 346의 스윕이 24h 뒤 `expired`로 바꾸므로, 그때부터
    이 잡의 대상이 된다(수명 사슬: pending → expired → 보존기간 경과 → 회수).

    기준 시각은 `resolved_at`(처리 시각), 없으면 `requested_at`(레거시·만료 행).
    보존기간 NULL/<1이면 비활성(파괴적 노브 바닥, learning 037).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        days = cfg.approval_retention_days
        await session.commit()

    if days is None or days < 1:
        return {"status": "disabled", "reason": "approval_retention_days<1", "deleted": 0}

    cutoff = datetime.now(UTC) - timedelta(days=days)
    # 처리된 것만(status != pending) + 기준 시각이 보존기간을 넘긴 것.
    stale = (Approval.status != "pending") & (
        safunc.coalesce(Approval.resolved_at, Approval.requested_at) < cutoff
    )
    async with SessionLocal() as session:
        rows = (await session.execute(select(Approval.approval_id).where(stale))).scalars().all()
        pending_total = (
            await session.execute(
                select(safunc.count()).select_from(Approval).where(Approval.status == "pending")
            )
        ).scalar_one()
        if dry_run:
            return {
                "status": "dry_run",
                "retention_days": days,
                "cutoff": cutoff.isoformat(),
                "would_delete": len(rows),
                "pending_protected": pending_total,
                "sample": list(rows[:20]),
            }
        if rows:
            await session.execute(delete(Approval).where(stale))
            await session.commit()
    log.info("승인 정리: %d행 삭제(보존 %d일, pending %d건 보호)", len(rows), days, pending_total)
    return {
        "status": "ok",
        "retention_days": days,
        "cutoff": cutoff.isoformat(),
        "deleted": len(rows),
        "pending_protected": pending_total,
    }


# 평가 추세(TrendChart)의 앵커 보호 — 문제집별 최근 N런은 나이와 무관하게 남긴다(스펙 351).
# 나이만으로 지우면 "성적 추이"가 통째로 사라진다(회수가 기능을 죽이면 안 된다).
_KEEP_RUNS_PER_DATASET = 10


async def cleanup_history(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — runner가 키워드 호출(계약)
    """실행 이력 회수(스펙 351) — eval_runs · batch_runs · memory_snapshots.

    셋 다 "무슨 일이 있었나"의 기록인데 **삭제 경로가 없었다**. 스펙 348로 배치가 실제로 돌기
    시작했으니 `batch_runs`는 이제 매시 쌓인다 — **청소부의 발자국도 치워야 한다.**

    `eval_runs`는 **문제집별 최근 10런을 나이와 무관하게 보존**한다(성적 추이 그래프의 앵커).
    `eval_case_results`는 FK CASCADE로 함께 사라진다(고아 없음).

    보존기간 NULL/<1이면 비활성(파괴적 노브 바닥, learning 037).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        days = cfg.history_retention_days
        await session.commit()

    if days is None or days < 1:
        return {"status": "disabled", "reason": "history_retention_days<1", "deleted": 0}

    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with SessionLocal() as session:
        # eval_runs — 문제집별 최근 N런 제외하고, cutoff보다 오래된 것.
        keep_ids = set()
        ds_ids = (await session.execute(select(EvalRun.dataset_id).distinct())).scalars().all()
        for ds in ds_ids:
            recent = (
                (
                    await session.execute(
                        select(EvalRun.id)
                        .where(EvalRun.dataset_id == ds)
                        .order_by(EvalRun.started_at.desc())
                        .limit(_KEEP_RUNS_PER_DATASET)
                    )
                )
                .scalars()
                .all()
            )
            keep_ids.update(recent)
        run_stmt = select(EvalRun.id).where(EvalRun.started_at < cutoff)
        if keep_ids:
            run_stmt = run_stmt.where(EvalRun.id.notin_(keep_ids))
        old_runs = (await session.execute(run_stmt)).scalars().all()

        old_batch = (
            (await session.execute(select(BatchRun.id).where(BatchRun.started_at < cutoff)))
            .scalars()
            .all()
        )
        old_snaps = (
            (
                await session.execute(
                    select(MemorySnapshot.id).where(MemorySnapshot.created_at < cutoff)
                )
            )
            .scalars()
            .all()
        )

        counts = {
            "eval_runs": len(old_runs),
            "batch_runs": len(old_batch),
            "memory_snapshots": len(old_snaps),
        }
        if dry_run:
            return {
                "status": "dry_run",
                "retention_days": days,
                "cutoff": cutoff.isoformat(),
                "would_delete": sum(counts.values()),
                "by_table": counts,
                "eval_runs_kept_per_dataset": _KEEP_RUNS_PER_DATASET,
            }

        if old_runs:
            # eval_case_results는 FK ondelete CASCADE로 함께 삭제된다(고아 없음).
            await session.execute(delete(EvalRun).where(EvalRun.id.in_(old_runs)))
        if old_batch:
            await session.execute(delete(BatchRun).where(BatchRun.id.in_(old_batch)))
        if old_snaps:
            await session.execute(delete(MemorySnapshot).where(MemorySnapshot.id.in_(old_snaps)))
        await session.commit()

    log.info(
        "실행 이력 정리: eval_runs %d · batch_runs %d · memory_snapshots %d (보존 %d일)",
        counts["eval_runs"],
        counts["batch_runs"],
        counts["memory_snapshots"],
        days,
    )
    return {
        "status": "ok",
        "retention_days": days,
        "cutoff": cutoff.isoformat(),
        "deleted": sum(counts.values()),
        "by_table": counts,
        "eval_runs_kept_per_dataset": _KEEP_RUNS_PER_DATASET,
    }


async def cleanup_memories(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — 러너가 키워드 호출(계약)
    """mem0 기억의 **도달 불가 고아** 회수(스펙 352 — 자원 감사 캠페인의 마지막 누수 테이블).

    회상은 오직 세 축(user_id·run_id·agent_id)으로만 일어난다. 한 행의 축이 **전부 죽은 소유자**를
    가리키면 그 행은 영영 회상되지 않는다(유령). **유령만** 지운다 — 살아있는 유저의 기억은 한 행도
    안 지운다(기억은 제품의 토대 기능, 회수가 기능을 죽이면 안 된다).

    유령을 만든 건 우리 청소부들이다: mem0는 별도 pgvector 테이블이라 FK가 없어, user-cleanup이
    유저를 지워도 그 기억이 남는다. 판정·SQL은 `memory.reclaim`에 격리(payload JSONB 결합).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        grace = cfg.memory_orphan_grace_days
        await session.commit()
    return await reclaim.reclaim_unreachable(dry_run=dry_run, grace_days=grace)
