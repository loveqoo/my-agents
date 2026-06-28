"""스펙 056 검증 — 세션 정리 턴 절은 카운터 Session.turns로 판정하되, 그 카운터가
진실이도록 seed를 0으로 고친 결과를 행사한다(실 DB + 실제 cleanup_sessions, dry-run, 무부수효과).

배경: 처음엔 turns 카운터를 불신하고 '실제 user 메시지 행 수'로 바꿨으나, codex 적대리뷰가
실결함을 짚었다 — persistHistory=false(윈도우 모드)는 메시지를 일부러 안 남기는데 turns는
계속 오르므로, 100턴 윈도우 세션(메시지 0행)이 저턴으로 오인돼 삭제된다. 즉 turns는 메시지
행의 캐시가 아니라 *더 완전한 진실*(turns ≥ 메시지행수)이고, 부풀린 거짓말은 seed 하나였다.
→ jobs는 카운터 기반 유지, seed turns만 0으로 진실화(learning 059).

핵심 단언:
  - turns=0 · 오래됨 → 삭제(시드형 빈 세션).
  - ★ turns=100 · 메시지 0행 · 오래됨 → **보존**(윈도우 모드, codex 회귀 가드 — 카운터가 진실).
  - turns=10 · 메시지 있음 · 오래됨 → 보존.
  - 최근활동(IDLE_GUARD 내) turns=0 → 보존. HIL pending turns=0 → 보존(049 가드).
  - 나이 절 단독·disabled no-op 회귀.

실행: .venv/bin/python tests/verify_056_session_cleanup_counter.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, select  # noqa: E402

from api.batch.jobs import cleanup_sessions  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent, Approval, BatchConfig, Message, Session  # noqa: E402

_fails: list[str] = []
PREFIX = "sess_v056_"
OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def sid(tag: str) -> str:
    return f"{PREFIX}{tag}"


async def _add_session(sess, agent, tag, *, turns, msgs, last_activity, status="active"):
    s = Session(
        session_id=sid(tag), agent_pk=agent.id, channel="test",
        status=status, turns=turns, tokens=0, last_activity=last_activity,
    )
    sess.add(s)
    await sess.flush()
    for i in range(msgs):
        sess.add(Message(session_pk=s.id, role="user", content=f"u{i}"))
        sess.add(Message(session_pk=s.id, role="assistant", content=f"a{i}"))


async def _cleanup_prefix(sess):
    rows = (await sess.execute(
        select(Session.id).where(Session.session_id.like(PREFIX + "%"))
    )).scalars().all()
    if rows:
        await sess.execute(delete(Message).where(Message.session_pk.in_(rows)))
    await sess.execute(delete(Approval).where(Approval.session_id.like(PREFIX + "%")))
    await sess.execute(delete(Session).where(Session.session_id.like(PREFIX + "%")))


async def main():
    now = datetime.now(timezone.utc)
    async with SessionLocal() as sess:
        agent = (await sess.execute(select(Agent).limit(1))).scalars().first()
        if agent is None:
            raise RuntimeError("검증 불가: agents 비어있음(시드 필요)")
        cfg = (await sess.execute(select(BatchConfig).limit(1))).scalars().first()
        if cfg is None:
            cfg = BatchConfig(); sess.add(cfg); await sess.flush()
        orig = (cfg.session_retention_days, cfg.min_session_turns)

        await _cleanup_prefix(sess)
        await _add_session(sess, agent, "empty_low", turns=0, msgs=0, last_activity=OLD)
        await _add_session(sess, agent, "windowed_high", turns=100, msgs=0, last_activity=OLD)  # ★ codex
        await _add_session(sess, agent, "normal_high", turns=10, msgs=6, last_activity=OLD)
        await _add_session(sess, agent, "recent_low", turns=0, msgs=0, last_activity=now)
        await _add_session(sess, agent, "hil_low", turns=0, msgs=0, last_activity=OLD)
        sess.add(Approval(approval_id=sid("apr"), session_id=sid("hil_low"), status="pending"))
        await sess.commit()

    try:
        # ── Phase 1: 턴 절(카운터 turns < 4) ──
        async with SessionLocal() as sess:
            cfg = (await sess.execute(select(BatchConfig).limit(1))).scalars().first()
            cfg.session_retention_days = None
            cfg.min_session_turns = 4
            await sess.commit()
        res = await cleanup_sessions(dry_run=True)
        sample = set(res.get("sample", []))
        mine = {s for s in sample if s.startswith(PREFIX)}
        check(res.get("status") == "dry_run", "phase1 dry_run 상태")
        no_trunc = res.get("would_delete", 0) == len(res.get("sample", []))
        check(no_trunc, f"sample 비트렁케이트(would_delete={res.get('would_delete')}, sample={len(sample)})")
        check(sid("empty_low") in mine, "turns=0 빈 세션 → 삭제(시드형)")
        check(sid("windowed_high") not in mine, "★ turns=100·메시지0행 → 보존(윈도우모드, codex 회귀 가드)")
        check(sid("normal_high") not in mine, "turns=10 정상 세션 → 보존")
        check(sid("recent_low") not in mine, "최근활동 turns=0 → 보존(IDLE_GUARD)")
        check(sid("hil_low") not in mine, "HIL pending turns=0 → 보존(049 가드)")

        # ── Phase 2: 나이 절 단독(회귀) ──
        async with SessionLocal() as sess:
            cfg = (await sess.execute(select(BatchConfig).limit(1))).scalars().first()
            cfg.session_retention_days = 1
            cfg.min_session_turns = None
            await sess.commit()
        res2 = await cleanup_sessions(dry_run=True)
        m2 = {s for s in res2.get("sample", []) if s.startswith(PREFIX)}
        check(sid("windowed_high") in m2, "나이절: 오래된 세션 대상(턴 무관)")
        check(sid("recent_low") not in m2, "나이절: 최근 세션 보존")
        check(sid("hil_low") not in m2, "나이절: HIL pending 제외 가드 유지")

        # ── Phase 3: 둘 다 비활성 → disabled no-op ──
        async with SessionLocal() as sess:
            cfg = (await sess.execute(select(BatchConfig).limit(1))).scalars().first()
            cfg.session_retention_days = None
            cfg.min_session_turns = None
            await sess.commit()
        res3 = await cleanup_sessions(dry_run=True)
        check(res3.get("status") == "disabled", "둘 다 비활성 → disabled no-op")
    finally:
        async with SessionLocal() as sess:
            cfg = (await sess.execute(select(BatchConfig).limit(1))).scalars().first()
            cfg.session_retention_days, cfg.min_session_turns = orig
            await _cleanup_prefix(sess)
            await sess.commit()

    print()
    if _fails:
        print(f"FAIL: {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("VERIFY056_OK — 카운터 기반 정리: 빈 세션 삭제·윈도우모드 고턴 세션 보존")


asyncio.run(main())
