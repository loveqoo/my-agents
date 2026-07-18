"""테스트 유저 정리 — jobs.py에서 분할(스펙 395 P4, 순수 이동).

casbin purge=User delete 동일 tx·enforcer reload=commit 후 순서 보존(스펙 050 적대리뷰 #4·#5).
가드(패턴·keep-list·최후 super)는 jobs_guards. 파사드는 jobs.py(재수출 계약).
"""

import logging
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy import func as safunc
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import User
from .jobs_guards import _protect_last_supers, _survives_keep_list, is_delete_all_pattern
from .jobs_shared import _get_config

log = logging.getLogger("api.batch.jobs")


async def _purge_casbin_rules(session: AsyncSession, ids: list[uuid.UUID]) -> None:
    """삭제 유저의 Casbin grouping/policy 행 제거(dangling 권한 누수 방지) — User 삭제와 같은
    트랜잭션(DB 원자성). casbin_rule은 ORM 모델이 없어 raw SQL. v0=삭제 유저 UUID인 행을 g·p 둘 다
    제거한다 — 현재는 user-subject가 g뿐이지만 모델이 per-user p-정책을 허용하므로 미래의 dangling
    p도 막는다(적대리뷰 #5). v0이 role명('admin' 등)인 글로벌 p-정책은 UUID와 안 겹쳐 안전하다."""
    uid_strs = [str(i) for i in ids]
    await session.execute(
        text("DELETE FROM casbin_rule WHERE ptype IN ('g','p') AND v0 = ANY(:uids)"),
        {"uids": uid_strs},
    )


async def _reload_enforcer_after_user_delete() -> None:
    """인프로세스(API 트리거) 메모리 enforcer를 reload해 삭제된 grant 잔존을 동기화(적대리뷰 #4).
    잡이 별 프로세스로 돌면 enforcer 미초기화(_enforcer=None)라 조용히 스킵 — DB가 진실원이라 무해."""
    try:
        from .. import authz

        if authz._enforcer is not None:
            await authz._enforcer.load_policy()
    except Exception as exc:
        log.warning("user-cleanup: casbin enforcer reload 실패(무해, DB는 정리됨): %s", exc)


async def cleanup_test_users(*, dry_run: bool, run_id: uuid.UUID | None = None) -> dict:  # noqa: ARG001 — runner가 키워드 호출(계약)
    """테스트 유저 정리(스펙 050, #13) — 이메일이 config 패턴(LIKE) 일치 AND keep-list 제외인 유저 삭제.
    가장 비가역이라 바닥 3겹(learning 037):

    1. 패턴 NULL → disabled no-op(명시 설정 전엔 절대 삭제 안 함). 패턴 `%`/빈 → delete-all 가드로 거부.
    2. 하드코딩 keep-list(부트스트랩 admin@·데모 alice@)는 패턴 일치해도 제외.
    3. 마지막 슈퍼유저 보호 — 삭제로 super가 0이 되면 매치된 super 전부 보존(콘솔 잠금 방지).

    cascade·정합성: accesstoken은 user_id FK CASCADE(DB 처리). sessions.user_id는 plain String →
    고아 문자열 무해(049가 정리). Casbin grouping/policy(casbin_rule v0=user_id)는 dangling이라 같은
    실행에서 제거(권한 누수 방지). mem0(user_id 축)는 별 저장소 → 범위 밖(debt §7).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        pattern = cfg.test_user_email_pattern
        # 바닥 1a — NULL/빈 = 비활성(명시 설정 전엔 no-op).
        if not pattern or not pattern.strip():
            log.info("user-cleanup: 패턴 비활성(pattern=%r) → no-op", pattern)
            return {"status": "disabled", "deleted": 0}
        # 바닥 1b — 광범위(전체) 삭제 패턴 거부. `%`만이 아니라 `%@%`·`%a%`처럼 리터럴이 약해 거의
        # 전부를 매치하는 패턴도 막는다(적대리뷰 #1). API 422 외 여기 한 겹 더(같은 함수 공유).
        if is_delete_all_pattern(pattern):
            log.warning("user-cleanup: 광범위 삭제 패턴(%r) 거부", pattern)
            return {"status": "rejected", "reason": "delete_all_pattern", "deleted": 0}

        rows = (
            await session.execute(
                select(User.id, User.email, User.is_superuser).where(User.email.like(pattern))
            )
        ).all()
        candidates = [r for r in rows if _survives_keep_list(r[1])]

        total_supers = (
            await session.execute(
                select(safunc.count()).select_from(User).where(User.is_superuser.is_(True))
            )
        ).scalar_one()
        candidates, protected_super_emails = _protect_last_supers(candidates, total_supers)

        ids = [r[0] for r in candidates]
        meta = {
            "pattern": pattern,
            "matched": len(rows),
            "protected_superusers": protected_super_emails,
        }
        sample = [{"email": r[1], "is_superuser": r[2]} for r in candidates[:20]]

        if dry_run:
            log.info(
                "user-cleanup DRY-RUN: 패턴 %r 매치 %d → 삭제대상 %d (super 보존 %d)",
                pattern,
                len(rows),
                len(ids),
                len(protected_super_emails),
            )
            return {"status": "dry_run", **meta, "would_delete": len(ids), "sample": sample}

        if not ids:
            return {"status": "ok", **meta, "deleted": 0}
        await _purge_casbin_rules(session, ids)
        # Core bulk DELETE — accesstoken은 user_id FK ondelete CASCADE라 DB가 정리.
        await session.execute(delete(User).where(User.id.in_(ids)))
        await session.commit()
    # DB는 정리됐다 — 메모리 enforcer의 잔존 grant만 동기화하면 된다.
    await _reload_enforcer_after_user_delete()
    log.info(
        "user-cleanup: %d 유저 삭제 (패턴 %r, super 보존 %d)",
        len(ids),
        pattern,
        len(protected_super_emails),
    )
    return {"status": "ok", **meta, "deleted": len(ids)}
