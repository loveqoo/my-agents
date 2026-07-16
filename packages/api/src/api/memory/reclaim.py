"""mem0 기억의 **도달 불가 고아** 회수 (스펙 352).

**왜 여기 있나**: `mem0_memories`는 mem0 소유의 pgvector 테이블이라 **우리 테이블과 FK가 없다.**
그래서 `user-cleanup`이 유저를, `session-cleanup`이 세션을, 관리자가 에이전트를 지워도 그 기억은
그대로 남는다 — **청소부의 발자국**이다(스펙 351과 같은 가족). 스펙 348로 청소부가 실제로 돌기
시작했으니 유령은 이제 꾸준히 생산된다.

**무엇을 지우나 — 도달 불가한 것만.** 회상은 오직 세 축(`SCOPE_AXES`)으로만 일어난다. 한 행이 지닌
축이 **전부 죽은 소유자**를 가리키면 그 행은 어떤 질의로도 영영 회상되지 않는다(= 유령). 살아있는
유저의 기억은 **한 행도 안 지운다** — 기억은 제품의 토대 기능이고, 회수가 기능을 죽이면 안 된다.

**payload JSONB 스키마 결합은 이 모듈에 격리한다**(`mem0_backend.list_page`와 같은 규율) — 배치 잡에
SQL을 흩뿌리지 않는다.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

log = logging.getLogger("api.memory.reclaim")

_MEM_TABLE = "mem0_memories"

# 축 → "살아있음"의 근거(축 값이 가리키는 테이블·컬럼).
#   user_id  = str(user.id)              → "user".id::text     (예약어라 쌍따옴표)
#   run_id   = sessions.session_id       → sessions.session_id ('sess-…')
#   agent_id = agents.agent_id           → agents.agent_id     ('agt-…')
_ALIVE = {
    "user_id": 'SELECT 1 FROM "user" u WHERE u.id::text = c.uid',
    "run_id": "SELECT 1 FROM sessions s WHERE s.session_id = c.rid",
    "agent_id": "SELECT 1 FROM agents a WHERE a.agent_id = c.aid",
}

# 도달 불가 = (축이 하나 이상 있고) 있는 축이 **전부** 죽었고, 유예 기간을 넘겼고, 나이를 알 수 있다.
# 나이 불명(created_at 없음/포맷 이탈)은 **보존**한다 — 스펙 346의 "나이를 모르면 안 지운다" 규칙.
_UNREACHABLE = f"""
WITH c AS (
  SELECT id,
         payload->>'user_id'  AS uid,
         payload->>'run_id'   AS rid,
         payload->>'agent_id' AS aid,
         CASE WHEN payload->>'created_at' ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}T'
              THEN (payload->>'created_at')::timestamptz END AS ts
  FROM {_MEM_TABLE}
)
SELECT id FROM c
WHERE ts IS NOT NULL AND ts < :cutoff
  AND (uid IS NOT NULL OR rid IS NOT NULL OR aid IS NOT NULL)
  AND (uid IS NULL OR NOT EXISTS ({_ALIVE["user_id"]}))
  AND (rid IS NULL OR NOT EXISTS ({_ALIVE["run_id"]}))
  AND (aid IS NULL OR NOT EXISTS ({_ALIVE["agent_id"]}))
"""

# 삭제는 **판정과 한 문장**이다(codex P1 — TOCTOU). `SELECT id` → `DELETE WHERE id IN (…)`로 나누면
# 그 사이에 유저/세션/에이전트가 되살아난(복구·import·수동 작업) 기억을 **되살아난 뒤에** 지운다.
# 삭제 시점에 조건을 **다시** 평가하게 한 문장으로 합치고, `RETURNING`으로 **실제 지운 행**을 센다
# (len(ids) 추정 아님 — 동시 삭제/충돌을 정직하게 반영).
# LIMIT 배치 루프: 유령이 수십만이어도 앱 메모리·파라미터 폭발 없이 나눠 지운다(codex P3).
_DELETE_BATCH = f"""
DELETE FROM {_MEM_TABLE}
WHERE id IN (SELECT id FROM ({_UNREACHABLE}) u LIMIT :batch)
RETURNING id
"""

_DELETE_STMT = text(_DELETE_BATCH)
_BATCH = 1000
_MAX_BATCHES = 1000  # 폭주 방지 — 한 실행당 최대 100만 행(넘으면 다음 실행이 이어서)


async def reclaim_unreachable(*, dry_run: bool, grace_days: int) -> dict:
    """도달 불가 기억 회수. 유예 <1이면 비활성(파괴적 노브 바닥, learning 037).

    반환: {"status": "disabled"|"dry_run"|"ok", "would_delete"|"deleted", "grace_days"}
    (status 문자열은 다른 배치 잡과 **같은 계약** — 관리자 화면이 잡별로 분기하지 않게.)
    """
    from ..db import SessionLocal  # 지연 임포트 — memory 패키지가 db를 정적 의존하지 않게

    if grace_days is None or grace_days < 1:
        return {"status": "disabled", "reason": "memory_orphan_grace_days<1", "deleted": 0}

    cutoff = datetime.now(UTC) - timedelta(days=grace_days)
    if dry_run:
        async with SessionLocal() as session:
            n = len((await session.execute(text(_UNREACHABLE), {"cutoff": cutoff})).all())
        log.info("memory-cleanup DRY-RUN: 도달 불가 기억 %d행 (유예 %d일)", n, grace_days)
        return {"status": "dry_run", "would_delete": n, "grace_days": grace_days}

    deleted = 0
    for _ in range(_MAX_BATCHES):
        async with SessionLocal() as session:
            got = len(
                (await session.execute(_DELETE_STMT, {"cutoff": cutoff, "batch": _BATCH})).all()
            )
            await session.commit()
        deleted += got
        if got < _BATCH:
            break
    if deleted:
        log.info("memory-cleanup: 도달 불가 기억 %d행 삭제 (유예 %d일)", deleted, grace_days)
    return {"status": "ok", "deleted": deleted, "grace_days": grace_days}
