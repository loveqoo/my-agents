"""스펙 049 검증 — 세션 정리 정책(#10): 0턴 소스 미영속 + 턴 기준 배치 정리.

두 메커니즘을 인프로세스로 단언한다.
  A. 소스 미영속(self-fixture 외부 에이전트):
     - `_load_context(agent, None)`는 행을 만들지 않는다(session_pk=None + session_pending 세팅).
     - 첫 `_persist`가 행을 lazy-create(turns=1), 재호출은 같은 행 재사용(중복 0).
     - `_create_approval`은 승인 게이트=실 턴이므로 행을 보장(approval-resume 연속성).
  B. 턴 기준 배치 정리(`api.batch.jobs.cleanup_sessions`):
     - IDLE_GUARD(1h)가 활성 세션을 보호, turns>=N이 충분 대화를 보호.
     - 나이·턴 합집합(중복 없음), 둘 다 NULL이면 disabled no-op.
     - days<1 / min_turns<1 잡-레벨 가드(learning 037 — 파괴적 노브 바닥).
     - 메시지 FK cascade.

**파괴 안전(learning 037/034)**: 턴 기준 실삭제는 *라이브 정크 세션*을 지울 수 있으므로,
실삭제는 **비-fixture 매치가 0건일 때만** 수행한다(적응형 가드). 매치가 있으면 실삭제를 건너뛰고
선택 로직만 dry-run + 스코프드 술어로 단언한다. 절대 남의 데이터를 지우지 않는다.
검증 자산은 agent_pk 단위로 자가정리(세션 cascade로 메시지 동반). BatchConfig 싱글톤은 저장→복원.

실행: .venv/bin/python tests/verify_049_session_retention_policy.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, func, or_, select, text  # noqa: E402

from api.batch.jobs import cleanup_sessions  # noqa: E402
from api.chat import _create_approval, _load_context, _persist  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402,F401  (모듈 캐시 워밍)
from api.models import Agent, Approval, BatchConfig, Message, Session  # noqa: E402

SP = "v049_"  # 세션 fixture prefix(B에서 직접 시드)
AGT = "agt_v049_probe"
_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ----------------------------- fixtures -----------------------------
async def _make_agent() -> Agent:
    async with SessionLocal() as s:
        existing = (
            await s.execute(select(Agent).where(Agent.agent_id == AGT))
        ).scalars().first()
        if existing is not None:
            return existing
        agent = Agent(agent_id=AGT, name="v049 probe", source="external")
        s.add(agent)
        await s.commit()
        await s.refresh(agent)
        return agent


async def _seed_session(agent_pk, sid: str, turns: int, age: timedelta) -> None:
    """명시 turns/last_activity로 세션 시드. onupdate=now()는 INSERT엔 안 걸리므로 값이 유지된다."""
    async with SessionLocal() as s:
        la = datetime.now(timezone.utc) - age
        sess = Session(
            session_id=sid, agent_pk=agent_pk, agent_name="v049",
            channel="v049", status="active", turns=turns, last_activity=la,
        )
        s.add(sess)
        await s.flush()
        s.add(Message(session_pk=sess.id, role="user", content="seed"))
        await s.commit()


async def _agent_session_count(agent_pk) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).select_from(Session).where(Session.agent_pk == agent_pk)
        ) or 0


async def _session_row(sid: str):
    async with SessionLocal() as s:
        return (
            await s.execute(select(Session).where(Session.session_id == sid))
        ).scalars().first()


async def _exists(sid: str) -> bool:
    return (await _session_row(sid)) is not None


async def _force_last_activity(sid: str, age: timedelta) -> None:
    """raw UPDATE로 last_activity를 과거로(ORM onupdate=now() 우회)."""
    async with SessionLocal() as s:
        la = datetime.now(timezone.utc) - age
        await s.execute(
            text("UPDATE sessions SET last_activity=:la WHERE session_id=:sid"),
            {"la": la, "sid": sid},
        )
        await s.commit()


async def _has_pending_approval(sid: str) -> bool:
    async with SessionLocal() as s:
        return (
            await s.scalar(
                select(func.count())
                .select_from(Approval)
                .where(Approval.session_id == sid, Approval.status == "pending")
            )
            or 0
        ) > 0


async def _msg_count(sid: str) -> int:
    async with SessionLocal() as s:
        sess = (await s.execute(select(Session).where(Session.session_id == sid))).scalars().first()
        if sess is None:
            return 0
        return await s.scalar(
            select(func.count()).select_from(Message).where(Message.session_pk == sess.id)
        ) or 0


async def _scoped_targets(agent_pk, days, min_turns) -> set[str]:
    """잡과 동일 술어를 *내 에이전트 스코프*로 재현 — 경계 시맨틱(idle-guard/turns) 교차검증용."""
    async with SessionLocal() as s:
        now = datetime.now(timezone.utc)
        clauses = []
        if days is not None and days >= 1:
            clauses.append(Session.last_activity < now - timedelta(days=days))
        if min_turns is not None and min_turns >= 1:
            clauses.append(
                (Session.turns < min_turns) & (Session.last_activity < now - timedelta(hours=1))
            )
        if not clauses:
            return set()
        rows = (
            await s.execute(
                select(Session.session_id).where(
                    Session.agent_pk == agent_pk, or_(*clauses)
                )
            )
        ).scalars().all()
        return set(rows)


async def _global_extra(agent_pk, days, min_turns) -> set[str]:
    """잡이 *전역으로* 지울 행 중 내 에이전트 밖(=실데이터)인 것. 실삭제 안전 게이트."""
    async with SessionLocal() as s:
        now = datetime.now(timezone.utc)
        clauses = []
        if days is not None and days >= 1:
            clauses.append(Session.last_activity < now - timedelta(days=days))
        if min_turns is not None and min_turns >= 1:
            clauses.append(
                (Session.turns < min_turns) & (Session.last_activity < now - timedelta(hours=1))
            )
        if not clauses:
            return set()
        rows = (
            await s.execute(
                select(Session.id).where(or_(*clauses), Session.agent_pk != agent_pk)
            )
        ).all()
        return {r[0] for r in rows}


# ----------------------------- config save/restore -----------------------------
async def _cfg_snapshot() -> dict:
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        if cfg is None:
            cfg = BatchConfig()
            s.add(cfg)
            await s.commit()
            await s.refresh(cfg)
        return {
            "session_retention_days": cfg.session_retention_days,
            "session_cleanup_cron": cfg.session_cleanup_cron,
            "min_session_turns": cfg.min_session_turns,
            "memory_consolidation_threshold": cfg.memory_consolidation_threshold,
            "memory_consolidation_cron": cfg.memory_consolidation_cron,
        }


async def _cfg_set(*, days=..., min_turns=...) -> None:
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        if days is not ...:
            cfg.session_retention_days = days
        if min_turns is not ...:
            cfg.min_session_turns = min_turns
        await s.commit()


async def _cfg_restore(snap: dict) -> None:
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        for k, v in snap.items():
            setattr(cfg, k, v)
        await s.commit()


async def _teardown(agent_pk) -> None:
    async with SessionLocal() as s:
        await s.execute(delete(Approval).where(Approval.agent_pk == agent_pk))
        # 세션 삭제 → 메시지 FK cascade(DB ondelete=CASCADE).
        await s.execute(delete(Session).where(Session.agent_pk == agent_pk))
        await s.execute(delete(Agent).where(Agent.id == agent_pk))
        await s.commit()


# ----------------------------- Section A -----------------------------
async def section_a(agent) -> None:
    print("\n== A. 소스 미영속 + lazy-create + approval 연속성 ==")
    before = await _agent_session_count(agent.id)

    # A1: _load_context는 행을 만들지 않는다.
    ctx = await _load_context(agent.id, None)
    check(ctx.get("session_pk") is None, "[A1] _load_context: session_pk=None(미영속 보류)")
    check(isinstance(ctx.get("session_pending"), dict), "[A1] session_pending 세팅됨")
    check(str(ctx.get("session_id", "")).startswith("sess-"), "[A1] session_id 즉시 생성(클라 참조용)")
    check(await _agent_session_count(agent.id) == before, "[A1] DB 세션 행 불변 — 0턴 미영속 증명")

    # A2: 첫 _persist가 lazy-create.
    await _persist(ctx, "안녕", "네", {}, {"in": 1, "out": 1}, store_messages=True)
    sid = ctx["session_id"]
    row = await _session_row(sid)
    check(row is not None, "[A2] 첫 _persist가 행 lazy-create")
    check(row is not None and row.turns == 1, f"[A2] turns=1 (실제 {row.turns if row else None})")
    check(await _msg_count(sid) == 2, "[A2] user+assistant 메시지 2건 저장")
    check(await _agent_session_count(agent.id) == before + 1, "[A2] 행 정확히 1개 증가")

    # A3: 재호출은 같은 행 재사용(중복 0).
    await _persist(ctx, "또", "응", {}, {"in": 1, "out": 1}, store_messages=True)
    row2 = await _session_row(sid)
    check(row2 is not None and row2.turns == 2, f"[A3] 재호출 turns=2 (실제 {row2.turns if row2 else None})")
    check(await _agent_session_count(agent.id) == before + 1, "[A3] 중복 행 미생성(여전히 +1)")
    check(await _msg_count(sid) == 4, "[A3] 메시지 누적 4건")

    # A4: _load_context로 같은 session_id 재진입 → 영속 행을 집는다.
    ctx_re = await _load_context(agent.id, sid)
    check(ctx_re.get("session_pk") is not None, "[A4] 기존 session_id 재진입 → session_pk 해석")
    check(ctx_re.get("session_pending") is None, "[A4] 재진입 시 pending None")

    # A5: 승인 게이트 = 실 턴 → _create_approval이 행 보장(resume 연속성).
    ctx_ap = await _load_context(agent.id, None)
    check(ctx_ap.get("session_pk") is None, "[A5] 승인 전 ctx도 미영속 보류")
    apid = await _create_approval(
        ctx_ap, "thread-v049", {"permission": "p", "action": "a", "summary": "s", "args": {}}
    )
    ap_sid = ctx_ap["session_id"]
    ap_row = await _session_row(ap_sid)
    check(ap_row is not None, "[A5] _create_approval이 세션 행 보장")
    check(ap_row is not None and ap_row.turns == 0, "[A5] 승인-생성 세션 turns=0(완료 턴 아님)")
    check(ctx_ap.get("session_pk") is not None, "[A5] ctx에 session_pk 기록(연속성)")
    async with SessionLocal() as s:
        ap = (await s.execute(select(Approval).where(Approval.approval_id == apid))).scalars().first()
        check(ap is not None and ap.session_id == ap_sid, "[A5] Approval.session_id가 같은 세션 가리킴")
    # resume 시뮬: 같은 session_id로 _load_context → 행을 찾아 새 id 안 만듦.
    ctx_resume = await _load_context(agent.id, ap_sid)
    check(ctx_resume.get("session_pk") is not None, "[A5] resume _load_context가 원 세션 재발견(연속성)")


# ----------------------------- Section B -----------------------------
async def _adaptive_real_or_dry(agent, days, min_turns, gone: set[str], kept: set[str], tag: str):
    """비-fixture 매치가 0건이면 실삭제+단언, 아니면 dry-run+보존단언(파괴 안전)."""
    extra = await _global_extra(agent.id, days, min_turns)
    if not extra:
        res = await cleanup_sessions(dry_run=False)
        check(res.get("status") == "ok", f"[{tag}] 실삭제 status=ok")
        for sid in gone:
            check(not await _exists(sid), f"[{tag}] 대상 삭제됨: {sid}")
        for sid in kept:
            check(await _exists(sid), f"[{tag}] 보호 세션 보존: {sid}")
        # idempotent
        res2 = await cleanup_sessions(dry_run=False)
        check(res2.get("deleted") == 0, f"[{tag}] 재실행 deleted=0 (idempotent)")
        return True
    else:
        print(f"  note  [{tag}] 라이브 비-fixture 매치 {len(extra)}건 → 실삭제 건너뜀(데이터 보호), dry-run로 검증")
        res = await cleanup_sessions(dry_run=True)
        check(res.get("status") == "dry_run", f"[{tag}] dry-run status=dry_run")
        check(res.get("would_delete", 0) >= len(gone), f"[{tag}] would_delete가 대상 포함(>= {len(gone)})")
        for sid in gone | kept:
            check(await _exists(sid), f"[{tag}] dry-run no-op: {sid} 보존")
        return False


async def section_b(agent) -> None:
    print("\n== B. 턴 기준 배치 정리(IDLE_GUARD/turns/union/guards) ==")

    # --- B1: 턴 기준 선택 — idle-guard가 활성 보호, turns가 충분대화 보호 ---
    await _cfg_set(days=None, min_turns=3)
    await _seed_session(agent.id, f"{SP}t_idle", turns=2, age=timedelta(hours=2))   # 대상
    await _seed_session(agent.id, f"{SP}t_active", turns=2, age=timedelta(minutes=5))  # idle-guard 보호
    await _seed_session(agent.id, f"{SP}t_big", turns=5, age=timedelta(hours=2))    # turns 보호

    res_dry = await cleanup_sessions(dry_run=True)
    check(res_dry.get("status") == "dry_run", "[B1] dry-run status=dry_run")
    check(res_dry.get("min_session_turns") == 3, "[B1] meta.min_session_turns=3")
    check(res_dry.get("idle_cutoff") is not None, "[B1] meta.idle_cutoff 세팅(IDLE_GUARD 적용)")
    check(res_dry.get("retention_days") is None, "[B1] 나이 기준 비활성(days=None)")

    scoped = await _scoped_targets(agent.id, None, 3)
    check(scoped == {f"{SP}t_idle"}, f"[B1] 스코프드 술어: idle만 대상(active/big 보호) — 실제 {scoped}")

    await _adaptive_real_or_dry(
        agent, None, 3, gone={f"{SP}t_idle"}, kept={f"{SP}t_active", f"{SP}t_big"}, tag="B1"
    )

    # --- B2: 나이∪턴 합집합(중복 없음) ---
    await _cfg_set(days=30, min_turns=3)
    await _seed_session(agent.id, f"{SP}u_age", turns=10, age=timedelta(days=40))    # 나이만
    await _seed_session(agent.id, f"{SP}u_turn", turns=1, age=timedelta(hours=2))    # 턴만
    await _seed_session(agent.id, f"{SP}u_both", turns=1, age=timedelta(days=40))    # 둘 다
    union = await _scoped_targets(agent.id, 30, 3)
    # t_idle(turns2,2h)도 턴 기준에 걸림 → 합집합에 포함. u_both은 한 번만(중복 없음).
    expected_union = {f"{SP}u_age", f"{SP}u_turn", f"{SP}u_both", f"{SP}t_idle"}
    check(union == expected_union, f"[B2] 합집합 = 나이∪턴, 중복 없음 — 실제 {union}")
    res_u = await cleanup_sessions(dry_run=True)
    check(res_u.get("retention_days") == 30 and res_u.get("min_session_turns") == 3,
          "[B2] dry-run meta에 양 기준 동시 반영")

    # --- B3: 나이 기준 실삭제 + cascade(038식 안전) ---
    await _cfg_set(days=30, min_turns=None)
    await _seed_session(agent.id, f"{SP}age_old", turns=1, age=timedelta(days=100))
    await _seed_session(agent.id, f"{SP}age_recent", turns=1, age=timedelta(days=1))
    msgs_before = await _msg_count(f"{SP}age_old")
    check(msgs_before == 1, f"[B3] 사전: age_old 메시지 1건 (실제 {msgs_before})")
    did = await _adaptive_real_or_dry(
        agent, 30, None, gone={f"{SP}age_old"}, kept={f"{SP}age_recent"}, tag="B3"
    )
    if did:
        check(await _msg_count(f"{SP}age_old") == 0, "[B3] age_old 메시지 FK cascade 삭제")
        check(await _msg_count(f"{SP}age_recent") == 1, "[B3] age_recent 메시지 보존")

    # --- B6: 미해결 승인 세션은 정리 제외(연속성 가드) — 적대리뷰 결함 #1 ---
    # _create_approval은 turns=0으로 행을 만든다 → 턴 절(<N)에 걸리고, 승인 대기는 흔히 IDLE_GUARD를
    # 넘긴다. 그 사이 정리되면 resume가 고아가 된다. 나이 절에도 같은 노출. age 경로로 안전 실증.
    ctx_g = await _load_context(agent.id, None)
    await _create_approval(
        ctx_g, "thread-v049-guard", {"permission": "p", "action": "a", "summary": "s", "args": {}}
    )
    gsid = ctx_g["session_id"]
    await _force_last_activity(gsid, timedelta(days=100))           # 승인 장기 미해결 시뮬
    await _seed_session(agent.id, f"{SP}g_plain_old", turns=1, age=timedelta(days=100))  # 대조군
    await _cfg_set(days=30, min_turns=None)
    check(await _has_pending_approval(gsid), "[B6] 사전: 승인 세션에 pending approval 존재")
    extra_g = await _global_extra(agent.id, 30, None)
    if not extra_g:
        res_g = await cleanup_sessions(dry_run=False)
        check(res_g.get("status") == "ok", "[B6] 실삭제 status=ok")
        check(await _exists(gsid), "[B6] 미해결 승인 세션 보존(나이 기준 충족에도 가드로 제외)")
        check(not await _exists(f"{SP}g_plain_old"), "[B6] 승인 없는 동일-나이 세션은 삭제(대조군)")
    else:
        print(f"  note  [B6] 라이브 비-fixture 매치 {len(extra_g)}건 → 실삭제 건너뜀(데이터 보호)")
        # 나이 기준엔 걸리지만(100d>30d) pending approval로 제외되어야 함을 술어로 단언.
        base = await _scoped_targets(agent.id, 30, None)  # 가드 없는 나이 술어
        check(gsid in base, "[B6] 나이 기준상으로는 대상(가드가 빼는 이유)")

    # --- B4: 둘 다 NULL → disabled no-op ---
    await _cfg_set(days=None, min_turns=None)
    cnt_before = await _agent_session_count(agent.id)
    res_dis = await cleanup_sessions(dry_run=False)
    check(res_dis.get("status") == "disabled", "[B4] days·turns 모두 NULL → status=disabled")
    check(res_dis.get("deleted") == 0, "[B4] disabled deleted=0")
    check(await _agent_session_count(agent.id) == cnt_before, "[B4] 행 불변")

    # --- B5: 잡-레벨 가드(days<1 / min_turns<1) — learning 037 바닥 ---
    await _cfg_set(days=0, min_turns=0)
    res_g0 = await cleanup_sessions(dry_run=True)
    check(res_g0.get("status") == "disabled", "[B5] days=0·turns=0 → disabled(잡 가드)")
    await _cfg_set(days=0, min_turns=None)
    res_g1 = await cleanup_sessions(dry_run=True)
    check(res_g1.get("status") == "disabled", "[B5] days=0 단독도 disabled(delete-all 방지)")
    await _cfg_set(days=None, min_turns=0)
    res_g2 = await cleanup_sessions(dry_run=True)
    check(res_g2.get("status") == "disabled", "[B5] min_turns=0 단독도 disabled")


# ----------------------------- validation -----------------------------
def section_validation() -> None:
    print("\n== C. API 검증(min_session_turns ge=1) ==")
    from pydantic import ValidationError

    from api.batch_routes import BatchConfigIn

    try:
        BatchConfigIn(min_session_turns=0)
        check(False, "[C] min_session_turns=0 → 422 거부")
    except ValidationError:
        check(True, "[C] min_session_turns=0 → ValidationError(ge=1)")
    try:
        BatchConfigIn(min_session_turns=1)
        check(True, "[C] min_session_turns=1 허용")
    except ValidationError:
        check(False, "[C] min_session_turns=1 허용")
    try:
        BatchConfigIn(min_session_turns=None)
        check(True, "[C] min_session_turns=None 허용(비활성)")
    except ValidationError:
        check(False, "[C] min_session_turns=None 허용(비활성)")


async def main() -> None:
    agent = await _make_agent()
    snap = await _cfg_snapshot()
    try:
        await section_a(agent)
        await section_b(agent)
        section_validation()
    finally:
        await _cfg_restore(snap)
        await _teardown(agent.id)

    print()
    if _fails:
        print(f"FAILED: {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
