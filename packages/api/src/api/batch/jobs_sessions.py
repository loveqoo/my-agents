"""세션 정리 잡 — jobs.py에서 분할(스펙 395 P5, 순수 이동).

나이∪턴 합집합·pending approval 양 절 AND 제외·turns 진실원(스펙 038/049/056 계약 보존).
파사드는 jobs.py(재수출 계약).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, delete, exists, or_, select

from ..db import SessionLocal
from ..models import Approval, Session
from .jobs_shared import _get_config

log = logging.getLogger("api.batch.jobs")

# 턴 기준 정리(스펙 049, #10)의 활성 세션 보호창. turns<N이어도 최근 IDLE_GUARD 안에 활동한
# 세션은 "진행 중"으로 보고 절대 삭제하지 않는다. 어드민 노브가 아니라 내부 안전 상수(옵션3 선택
# 반영) — cron은 보통 일 단위라 1시간이면 진행 중 대화를 안전하게 비껴간다.
_TURN_CLEANUP_IDLE_GUARD = timedelta(hours=1)


def _age_criterion_active(days: int | None) -> bool:
    """나이 절 활성 여부 — API ge=1 밖 한 겹 더(방어: days=0이면 delete-all footgun)."""
    return days is not None and days >= 1


def _turn_criterion_active(min_turns: int | None) -> bool:
    """턴 절 활성 여부 — API ge=1 밖 한 겹 더(방어: min_turns=0이면 delete-all footgun)."""
    return min_turns is not None and min_turns >= 1


def _session_cleanup_clauses(
    min_turns: int | None,
    age_active: bool,
    turn_active: bool,
    age_cutoff: datetime | None,
    idle_cutoff: datetime | None,
) -> list:
    """삭제 대상 판정 절 목록(나이 절 + 턴 절) — 조건식은 스펙 038·049 원문 그대로."""
    clauses = []
    if age_active:
        clauses.append(Session.last_activity < age_cutoff)
    if turn_active:
        # 턴 절은 카운터 Session.turns로 판정한다 — turns는 메시지 행의 캐시가 아니라 **더
        # 완전한 진실**이다(스펙 056). _persist가 턴마다 +1 하는데, persistHistory=false(윈도우
        # 모드, schemas.py)면 메시지 행을 일부러 안 남기므로 turns ≥ 메시지행수가 항상 성립한다.
        # 즉 메시지 행 수로 세면 100턴 윈도우 세션(메시지 0행)을 저턴으로 오인해 지운다(codex
        # 적대리뷰 결함). turns를 부풀린 유일한 거짓말은 seed였고 그건 seed에서 0으로 고쳤다
        # (learning 058·059) — 카운터를 신호로 두고 거짓말의 출처를 고치는 게 옳다.
        # 활성 보호: 최근 활동 세션은 turns<N이어도 제외(idle_cutoff보다 오래된 것만).
        clauses.append((Session.turns < min_turns) & (Session.last_activity < idle_cutoff))
    return clauses


def _pending_approval_clause() -> ColumnElement[bool]:
    """미해결 승인(HIL) 세션 제외 술어 — 절대 삭제 안 함. _create_approval이 turns=0으로
    lazy-create한 세션이라 턴 절(<N)에 걸리고, 승인 대기는 흔히 IDLE_GUARD(1h)를 넘긴다. 그 사이
    정리되면 resume_approval의 _load_context가 행을 못 찾아 새 id를 만들어 대화를 고아로 만든다
    (적대리뷰 결함 #1, 스펙 049). 나이 절에도 동일 노출이므로 양 절에 걸쳐 AND로 제외한다."""
    return (
        exists()
        .where(Approval.session_id == Session.session_id)
        .where(Approval.status == "pending")
    )


def _session_cleanup_meta(
    days: int | None,
    min_turns: int | None,
    age_active: bool,
    turn_active: bool,
    age_cutoff: datetime | None,
    idle_cutoff: datetime | None,
) -> dict:
    """BatchRun.summary 메타 — 비활성 절의 값은 None."""
    return {
        "retention_days": days if age_active else None,
        "cutoff": age_cutoff.isoformat() if age_cutoff else None,
        "min_session_turns": min_turns if turn_active else None,
        "idle_cutoff": idle_cutoff.isoformat() if idle_cutoff else None,
    }


def _cleanup_criteria_labels(
    age_cutoff: datetime | None, min_turns: int | None, turn_active: bool
) -> tuple:
    """로그 표기용 (나이 기준, 턴 기준) 라벨 — 비활성 절은 'off'."""
    return (
        age_cutoff.isoformat() if age_cutoff else "off",
        min_turns if turn_active else "off",
    )


async def cleanup_sessions(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — runner가 키워드 호출(계약)
    """세션 정리 — 두 기준의 **합집합**(스펙 038 나이 + 스펙 049 턴). 메시지는 FK ondelete CASCADE로
    DB가 자동 삭제(messages.session_pk).

    - 나이 절: `last_activity < now() - retention_days`. retention_days NULL/<1이면 이 절 비활성.
    - 턴 절: `turns < min_session_turns AND last_activity < now() - IDLE_GUARD`(이탈 저턴 세션).
      min_session_turns NULL/<1이면 이 절 비활성. IDLE_GUARD가 활성 세션을 보호.
    - 둘 다 비활성이면 no-op(disabled) — 명시 설정 전엔 절대 삭제 안 함.
    - 둘 다 last_activity 단조 기준이라 idempotent(이미 지워진 행은 다시 못 찾음).
    - mem0 장기기억(별 저장소, user_id/run_id 키)은 건드리지 않는다 — 전사 ≠ 장기기억(#6은 039).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        days = cfg.session_retention_days
        min_turns = cfg.min_session_turns
        now = datetime.now(UTC)

        age_active = _age_criterion_active(days)
        turn_active = _turn_criterion_active(min_turns)
        if not age_active and not turn_active:
            log.info("session-cleanup: 나이·턴 기준 모두 비활성 → no-op")
            return {"status": "disabled", "deleted": 0}

        age_cutoff = now - timedelta(days=days) if age_active else None
        idle_cutoff = now - _TURN_CLEANUP_IDLE_GUARD if turn_active else None
        clauses = _session_cleanup_clauses(
            min_turns, age_active, turn_active, age_cutoff, idle_cutoff
        )

        rows = (
            await session.execute(
                select(Session.id, Session.session_id).where(
                    or_(*clauses), ~_pending_approval_clause()
                )
            )
        ).all()
        ids = [r[0] for r in rows]

        meta = _session_cleanup_meta(
            days, min_turns, age_active, turn_active, age_cutoff, idle_cutoff
        )
        age_label, turn_label = _cleanup_criteria_labels(age_cutoff, min_turns, turn_active)

        if dry_run:
            log.info(
                "session-cleanup DRY-RUN: 대상 %d건 (나이=%s, 턴<%s)",
                len(ids),
                age_label,
                turn_label,
            )
            return {
                "status": "dry_run",
                **meta,
                "would_delete": len(ids),
                "sample": [r[1] for r in rows[:20]],
            }

        if ids:
            # Core bulk DELETE — ORM cascade는 안 걸리지만 messages FK가 ondelete CASCADE라 DB가 정리.
            await session.execute(delete(Session).where(Session.id.in_(ids)))
            await session.commit()
        log.info("session-cleanup: %d건 삭제 (나이=%s, 턴<%s)", len(ids), age_label, turn_label)
        return {"status": "ok", **meta, "deleted": len(ids)}
