"""스펙 073 검증 — 세션 읽기 저장계층 타이밍 봉합을 EXPLAIN으로 *실측*.

070이 앱(파이썬) 계층을 단일화했어도, `session_id` 단독 unique 인덱스가 남으면 member 쿼리
`WHERE session_id=:id AND user_id=:own`에서 플래너가 그 단독 인덱스로 **타인-존재행을 heap-fetch**한 뒤
거부 vs 부재행은 인덱스 미스 → 저장계층 타이밍 델타 잔존(070 §적대 [P2]).

이 검증의 본질(learning 073 항목 2): "복합 인덱스가 존재한다"가 아니라 **"플래너가 실제로 그 복합을
선택해, 타인-존재행과 부재행이 동일 인덱스·동일 접근을 보인다"**를 `EXPLAIN (ANALYZE, BUFFERS)`로
측정한다(자가 단정 금지). 단독 unique를 고르면 봉합 무효 → FAIL로 드러난다.

측정 매트릭스(own=B 관점):
  [읽기] _get_session_or_404 member: WHERE session_id AND user_id
    R1 타인-존재행(A 소유 session_id) — 어떤 인덱스? 타인행 heap-fetch 하나?
    R2 부재행(없는 session_id) — 어떤 인덱스?
    → R1·R2가 *동일 복합 인덱스* 사용 + R1이 타인행을 Filter로 만지지 않음(인덱스 단계 미스).
  [resume] chat.py member: WHERE session_id AND agent_pk AND user_id
    S1 타인-존재행 / S2 부재행 — 동형.

플래너가 인덱스를 쓰게 충분한 행을 시드(seq-scan 회피). 자기정리(prefix).

실행: .venv/bin/python tests/verify_073_explain.py
"""
import asyncio
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, select, text  # noqa: E402

from api.db import SessionLocal, engine  # noqa: E402
from api.models import Agent, Session as Sess  # noqa: E402

PREFIX = "sess_v073_"
UID_A = "user_v073_A"
UID_B = "user_v073_B"
N_FILL = 600  # B 소유 더미 — 플래너가 인덱스를 선호하게 테이블을 키운다.

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _cleanup() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(Sess).where(Sess.session_id.like(f"{PREFIX}%")))
        await s.commit()


async def _seed_agent() -> uuid.UUID:
    """측정용 agent — 기존 첫 agent 재사용, 없으면 생성."""
    async with SessionLocal() as s:
        a = (await s.execute(select(Agent).limit(1))).scalar_one_or_none()
        if a is not None:
            return a.id
        a = Agent(agent_id=f"agt_v073_{uuid.uuid4().hex[:8]}", name="v073 probe", model="")
        s.add(a)
        await s.commit()
        return a.id


async def _seed_sessions(agent_pk: uuid.UUID) -> None:
    async with SessionLocal() as s:
        # 타인-존재 대상: A 소유 1행.
        s.add(Sess(session_id=f"{PREFIX}alien", agent_pk=agent_pk, user_id=UID_A, status="active"))
        # B 소유 더미 다수 — 인덱스 선호 유도.
        for i in range(N_FILL):
            s.add(Sess(session_id=f"{PREFIX}b{i}", agent_pk=agent_pk, user_id=UID_B, status="active"))
        await s.commit()
    # 플래너 통계 최신화.
    async with engine.connect() as c:
        await c.execute(text("ANALYZE sessions"))
        await c.commit()


def _walk(node: dict):
    """plan 트리를 평탄화."""
    yield node
    for ch in node.get("Plans", []) or []:
        yield from _walk(ch)


def _summarize(plan_json) -> dict:
    root = plan_json[0]["Plan"] if isinstance(plan_json, list) else plan_json["Plan"]
    idx_names, node_types, rows_removed = [], [], 0
    for n in _walk(root):
        node_types.append(n.get("Node Type"))
        if n.get("Index Name"):
            idx_names.append(n["Index Name"])
        rows_removed += int(n.get("Rows Removed by Filter", 0) or 0)
    # 루트 노드의 buffer는 자식 누적(=쿼리 전체). shared_hit+shared_read = 총 블록 접근수로,
    # 캐시 온도와 무관하게 결정적(히트/리드 분배만 캐시 의존, 합은 플랜·데이터 고정). 이게 타이밍의
    # 실제 지표 — 타인행 heap 1페이지를 더 만지면 total이 +1 된다(codex P1 #2: rows_removed보다 강함).
    shared_hit = int(root.get("Shared Hit Blocks", 0) or 0)
    shared_read = int(root.get("Shared Read Blocks", 0) or 0)
    return {
        "indexes": idx_names,
        "node_types": node_types,
        "rows_removed_by_filter": rows_removed,
        "shared_hit": shared_hit,
        "shared_read": shared_read,
        "total_blocks": shared_hit + shared_read,
    }


async def _explain(conn, sql: str, params: dict, warm: bool = True) -> dict:
    # warm: 측정 전 1회 실행해 페이지를 shared buffers로 끌어와 hit/read 분배를 안정화(total은 본디
    # 캐시 무관하나, 측정의 결정성을 높여 flaky 제거). 강제-solo 데모는 트랜잭션 내라 warm=False.
    q = text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
    if warm:
        await conn.execute(q, params)
    raw = (await conn.execute(q, params)).scalar()
    plan = raw if isinstance(raw, (list, dict)) else json.loads(raw)
    return _summarize(plan)


async def main() -> None:
    await _cleanup()
    agent_pk = await _seed_agent()
    await _seed_sessions(agent_pk)
    try:
        COMP = "ix_sessions_user_id_session_id"
        RCOMP = "ix_sessions_user_id_agent_pk_session_id"
        SOLO = "sessions_session_id_key"
        read_sql = "SELECT * FROM sessions WHERE session_id = :sid AND user_id = :own"
        resume_sql = ("SELECT * FROM sessions WHERE session_id = :sid "
                      "AND agent_pk = :apk AND user_id = :own")
        async with engine.connect() as c:
            r1 = await _explain(c, read_sql, {"sid": f"{PREFIX}alien", "own": UID_B})  # 타인-존재
            r2 = await _explain(c, read_sql, {"sid": f"{PREFIX}ghost", "own": UID_B})  # 부재

            print("[읽기 게이트] _get_session_or_404 member (WHERE session_id AND user_id)")
            print(f"  R1 타인-존재: indexes={r1['indexes']} removed_by_filter={r1['rows_removed_by_filter']} "
                  f"blocks(hit+read)={r1['total_blocks']}")
            print(f"  R2 부재    : indexes={r2['indexes']} removed_by_filter={r2['rows_removed_by_filter']} "
                  f"blocks(hit+read)={r2['total_blocks']}")
            check(COMP in r1["indexes"], f"R1 타인-존재가 복합 인덱스({COMP}) 사용")
            check(SOLO not in r1["indexes"], f"R1 타인-존재가 단독 unique({SOLO})를 타지 않음(heap-fetch 회피)")
            check(r1["indexes"] == r2["indexes"], "R1·R2 동일 인덱스 경로(타인-존재=부재)")
            check(r1["rows_removed_by_filter"] == 0,
                  f"R1 타인행을 Filter로 만지지 않음(인덱스 단계 미스) (got {r1['rows_removed_by_filter']})")
            # codex P1 #2: rows_removed보다 강한 *타이밍 지표* — 총 블록 접근수 동등(타인행 heap 미접근).
            check(r1["total_blocks"] == r2["total_blocks"],
                  f"R1·R2 buffer 총 블록 동등(타인-존재=부재, 타인 heap 미접근) "
                  f"(got {r1['total_blocks']} vs {r2['total_blocks']})")

            s1 = await _explain(c, resume_sql, {"sid": f"{PREFIX}alien", "apk": agent_pk, "own": UID_B})
            s2 = await _explain(c, resume_sql, {"sid": f"{PREFIX}ghost", "apk": agent_pk, "own": UID_B})
            print("[resume] chat member (WHERE session_id AND agent_pk AND user_id)")
            print(f"  S1 타인-존재: indexes={s1['indexes']} removed_by_filter={s1['rows_removed_by_filter']} "
                  f"blocks(hit+read)={s1['total_blocks']}")
            print(f"  S2 부재    : indexes={s2['indexes']} removed_by_filter={s2['rows_removed_by_filter']} "
                  f"blocks(hit+read)={s2['total_blocks']}")
            # codex P2 #3: resume 전용 복합을 *특정*해 단언(startswith는 (user_id,session_id)로도 통과해
            # 새 (user_id,agent_pk,session_id) 인덱스를 미입증). 단독 unique만 아니면 heap 회피는 성립하나,
            # resume 경로의 의도된 인덱스가 실제 선택됨을 못 박는다.
            check(RCOMP in s1["indexes"],
                  f"S1 타인-존재가 resume 전용 복합({RCOMP}) 사용 (got {s1['indexes']})")
            check(SOLO not in s1["indexes"],
                  f"S1 타인-존재가 단독 unique({SOLO})를 타지 않음")
            check(s1["indexes"] == s2["indexes"], "S1·S2 동일 인덱스 경로")
            check(s1["rows_removed_by_filter"] == 0,
                  f"S1 타인행을 Filter로 만지지 않음 (got {s1['rows_removed_by_filter']})")
            check(s1["total_blocks"] == s2["total_blocks"],
                  f"S1·S2 buffer 총 블록 동등 (got {s1['total_blocks']} vs {s2['total_blocks']})")

        # ── 반증(sensitivity) — 복합이 봉합의 *원인*임을 강제로 입증 (codex P1 #1) ──
        # 복합을 트랜잭션 내에서 가려 플래너가 solo unique(session_id, 1행 selective)를 쓰게 강제 →
        # 타인-존재행이 heap-fetch되어 buffer 델타가 *되돌아오는지* 측정. 되돌아오면: (a) 테스트가 델타에
        # 민감함(위 동등 단언이 우연 아님), (b) 복합 인덱스가 봉합의 실제 원인임이 반증으로 확정.
        # rollback이라 비파괴(인덱스 무손상). 주의: 이 데모는 측정이 "플래너 강제"가 아닌 "플래너 선택"임을
        # 드러낸다 — 운영 분포/통계에서 플래너가 solo로 회귀하면 델타 잔존(스펙 §대비 분기·정직 기록).
        async with engine.connect() as c:
            trans = await c.begin()
            try:
                await c.execute(text(f"DROP INDEX {COMP}"))
                await c.execute(text(f"DROP INDEX {RCOMP}"))
                f1 = await _explain(c, read_sql, {"sid": f"{PREFIX}alien", "own": UID_B}, warm=False)
                f2 = await _explain(c, read_sql, {"sid": f"{PREFIX}ghost", "own": UID_B}, warm=False)
            finally:
                await trans.rollback()
            print("[반증] 복합 제거→플래너 solo unique 강제 (트랜잭션 rollback, 비파괴)")
            print(f"  F1 타인-존재: indexes={f1['indexes']} removed_by_filter={f1['rows_removed_by_filter']} "
                  f"blocks(hit+read)={f1['total_blocks']}")
            print(f"  F2 부재    : indexes={f2['indexes']} removed_by_filter={f2['rows_removed_by_filter']} "
                  f"blocks(hit+read)={f2['total_blocks']}")
            check(SOLO in f1["indexes"],
                  f"강제: 복합 제거 시 플래너가 solo unique({SOLO}) 선택 (got {f1['indexes']})")
            check(f1["total_blocks"] != f2["total_blocks"],
                  f"강제(solo): 타인-존재 vs 부재 buffer 델타 *재출현* → 테스트 민감+복합이 봉합 원인 입증 "
                  f"(got {f1['total_blocks']} vs {f2['total_blocks']})")
    finally:
        await _cleanup()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")
