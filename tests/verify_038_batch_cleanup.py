"""스펙 038 검증 — 격리 배치 토대 + 세션 보존정리.

격리 배치 서비스의 작업 함수(`api.batch.jobs.cleanup_sessions`)와 runner(`run_job`)를 인프로세스로
단언한다. 검증용 세션은 고유 prefix(v038_)로 만들어 단언 후 삭제(자가정리). BatchConfig 싱글톤은
원래 값을 저장→복원한다(앱과 공유 1행). DB 필요(mock LLM 서버는 불필요 — 도구 호출 없음).

단언:
  1. dry-run은 no-op: would_delete가 오래된 세션만 집계 + DB 실제 행 수 불변.
  2. 실행: 오래된 세션 + 그 메시지(FK cascade) 삭제, 최근 세션·메시지는 보존.
  3. idempotent: 재실행 시 deleted=0(이미 지워짐).
  4. 비활성(retention_days=None): status=disabled + 행 불변.
  5. BatchRun 박제: running→ok + summary 건수. 작업 예외 시 status=error graceful(미raise).
  6. mem0 미접촉: 세션 삭제 전후 mem0_memories 행 수 불변(전사 ≠ 장기기억).

실행: .venv/bin/python tests/verify_038_batch_cleanup.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, func, select, text  # noqa: E402

from api.batch import jobs as jobs_mod  # noqa: E402
from api.batch.jobs import JOBS  # noqa: E402
from api.batch.runner import run_job  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402,F401  (모듈 캐시 워밍 — fastapi_users 등)
from api.models import Agent, BatchConfig, BatchRun, Message, Session  # noqa: E402

SP = "v038_"
_fails: list[str] = []
_run_ids: list = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _config():
    async with SessionLocal() as s:
        return (await s.execute(select(BatchConfig).limit(1))).scalars().first()


async def _set_retention(days):
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        cfg.session_retention_days = days
        await s.commit()


async def _count_sessions() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(Session).where(Session.session_id.like(f"{SP}%"))) or 0


async def _session_exists(sid: str) -> bool:
    async with SessionLocal() as s:
        return (await s.scalar(select(func.count()).select_from(Session).where(Session.session_id == sid)) or 0) > 0


async def _msg_count(sid: str) -> int:
    async with SessionLocal() as s:
        sess = (await s.execute(select(Session).where(Session.session_id == sid))).scalars().first()
        if sess is None:
            return 0
        return await s.scalar(select(func.count()).select_from(Message).where(Message.session_pk == sess.id)) or 0


async def _mem0_count():
    """mem0_memories 행 수(없으면 None → 단언 skip)."""
    try:
        async with SessionLocal() as s:
            return await s.scalar(text("select count(*) from mem0_memories"))
    except Exception:
        return None


async def _seed_sessions():
    """오래된 세션 2개(각 메시지 2개) + 최근 세션 1개(메시지 1개) 생성."""
    async with SessionLocal() as s:
        agent = (await s.execute(select(Agent).limit(1))).scalars().first()
        assert agent is not None, "시드 에이전트가 필요합니다"
        old_dt = datetime.now(timezone.utc) - timedelta(days=100)
        recent_dt = datetime.now(timezone.utc) - timedelta(days=1)
        specs = [
            (f"{SP}old_a", old_dt, 2),
            (f"{SP}old_b", old_dt, 2),
            (f"{SP}recent", recent_dt, 1),
        ]
        for sid, la, nmsg in specs:
            sess = Session(
                session_id=sid, agent_pk=agent.id, agent_name=agent.name or "t",
                channel="v038", status="completed", last_activity=la,
            )
            s.add(sess)
            await s.flush()
            for i in range(nmsg):
                s.add(Message(session_pk=sess.id, role="user", content=f"m{i}"))
        await s.commit()


async def _delete_test_sessions():
    """검증 세션·메시지만 삭제(BatchRun 감사행은 보존 — [5]에서 단언)."""
    async with SessionLocal() as s:
        col_ids = select(Session.id).where(Session.session_id.like(f"{SP}%"))
        await s.execute(delete(Message).where(Message.session_pk.in_(col_ids)))
        await s.execute(delete(Session).where(Session.session_id.like(f"{SP}%")))
        await s.commit()


async def _cleanup_db():
    await _delete_test_sessions()
    async with SessionLocal() as s:
        if _run_ids:
            await s.execute(delete(BatchRun).where(BatchRun.id.in_(_run_ids)))
        await s.commit()


async def main() -> None:
    orig = await _config()
    orig_days = orig.session_retention_days if orig else None
    orig_cron = orig.session_cleanup_cron if orig else None

    await _cleanup_db()
    try:
        # retention=30일 → old_a/old_b(100일)만 대상, recent(1일)은 보존.
        await _set_retention(30)
        await _seed_sessions()

        before = await _count_sessions()
        check(before == 3, f"[seed] 검증 세션 3개 생성 (실제 {before})")

        # --- [1] dry-run = no-op ---
        mem_before = await _mem0_count()
        res = await run_job("session-cleanup", dry_run=True)
        _run_ids.append(__import__("uuid").UUID(res["run_id"]))
        summ = res.get("summary", {})
        check(res["status"] == "ok", "[1] dry-run run_job status=ok")
        check(summ.get("status") == "dry_run", "[1] summary.status=dry_run")
        check(summ.get("would_delete") == 2, f"[1] would_delete=2 (실제 {summ.get('would_delete')})")
        check(await _count_sessions() == 3, "[1] dry-run 후 DB 행 수 불변(3) — no-op 증명")
        check(await _session_exists(f"{SP}old_a"), "[1] dry-run이 오래된 세션을 지우지 않음")
        # 미리보기 sample은 라이브 응답엔 있고(운영자 미리보기), 감사행엔 미영속(데이터 최소화).
        check(isinstance(summ.get("sample"), list) and len(summ["sample"]) == 2,
              f"[1] 라이브 응답에 sample 2건(미리보기) — 실제 {summ.get('sample')}")
        async with SessionLocal() as s:
            dry_row = await s.get(BatchRun, _run_ids[0])
            persisted = dry_row.summary or {} if dry_row else {}
            check("sample" not in persisted, "[1] 감사행 summary에는 sample 미영속(원시 식별자 미적재)")
            check(persisted.get("would_delete") == 2, "[1] 감사행 summary는 건수(would_delete)는 보존")

        # --- [2] 실행: 오래된 것 삭제 + cascade + 최근 보존 ---
        old_a_msgs = await _msg_count(f"{SP}old_a")
        recent_msgs_before = await _msg_count(f"{SP}recent")
        check(old_a_msgs == 2, f"[2] 사전: old_a 메시지 2개 (실제 {old_a_msgs})")
        res2 = await run_job("session-cleanup", dry_run=False)
        _run_ids.append(__import__("uuid").UUID(res2["run_id"]))
        summ2 = res2.get("summary", {})
        check(summ2.get("status") == "ok", "[2] 실행 summary.status=ok")
        check(summ2.get("deleted") == 2, f"[2] deleted=2 (실제 {summ2.get('deleted')})")
        check(not await _session_exists(f"{SP}old_a"), "[2] old_a 삭제됨")
        check(not await _session_exists(f"{SP}old_b"), "[2] old_b 삭제됨")
        check(await _session_exists(f"{SP}recent"), "[2] recent 보존됨")
        check(await _msg_count(f"{SP}old_a") == 0, "[2] old_a 메시지 cascade 삭제(0)")
        check(await _msg_count(f"{SP}recent") == recent_msgs_before == 1, "[2] recent 메시지 보존(1)")

        # --- [6] mem0 미접촉 ---
        mem_after = await _mem0_count()
        if mem_before is None:
            check(True, "[6] mem0_memories 테이블 없음 → skip(미접촉 자명)")
        else:
            check(mem_after == mem_before, f"[6] mem0 행 수 불변 ({mem_before}→{mem_after})")

        # --- [3] idempotent: 재실행 deleted=0 ---
        res3 = await run_job("session-cleanup", dry_run=False)
        _run_ids.append(__import__("uuid").UUID(res3["run_id"]))
        check(res3.get("summary", {}).get("deleted") == 0, "[3] 재실행 deleted=0 (idempotent)")

        # --- [4] 비활성: retention=None → disabled, 행 불변 ---
        await _set_retention(None)
        await _delete_test_sessions()  # 깨끗이 비우고 재시드(unique session_id 충돌 방지)
        await _seed_sessions()
        cnt_before_disabled = await _count_sessions()
        res4 = await run_job("session-cleanup", dry_run=False)
        _run_ids.append(__import__("uuid").UUID(res4["run_id"]))
        check(res4.get("summary", {}).get("status") == "disabled", "[4] retention=None → status=disabled")
        check(await _count_sessions() == cnt_before_disabled, "[4] 비활성 시 행 수 불변")

        # --- [4b] days<1 푸트건 가드: retention=0 → disabled, 행 불변(delete-all 방지) ---
        await _set_retention(0)
        cnt_before_zero = await _count_sessions()
        res4b = await run_job("session-cleanup", dry_run=False)
        _run_ids.append(__import__("uuid").UUID(res4b["run_id"]))
        check(res4b.get("summary", {}).get("status") == "disabled", "[4b] retention=0 → status=disabled(가드)")
        check(await _count_sessions() == cnt_before_zero, "[4b] retention=0이어도 행 불변(delete-all 방지)")

        # --- [5] BatchRun 박제 + error graceful ---
        async with SessionLocal() as s:
            run_row = await s.get(BatchRun, _run_ids[1])  # [2]의 실행
            check(run_row is not None and run_row.status == "ok", "[5] BatchRun status=ok 박제")
            check(run_row is not None and run_row.finished_at is not None, "[5] finished_at 박제")
            check(run_row is not None and (run_row.summary or {}).get("deleted") == 2, "[5] summary에 건수 박제")
            check(run_row is not None and run_row.dry_run is False, "[5] dry_run 플래그 박제")

        # error 경로: 일부러 실패하는 작업을 임시 등록 → run_job이 raise 없이 status=error 박제.
        async def _boom(*, dry_run: bool, run_id=None):
            raise RuntimeError("의도된 실패")

        JOBS["_v038_boom"] = _boom
        try:
            res5 = await run_job("_v038_boom", dry_run=False)
            _run_ids.append(__import__("uuid").UUID(res5["run_id"]))
            check(res5["status"] == "error", "[5] 작업 예외 → run_job status=error (미raise)")
            check("RuntimeError" in (res5.get("error") or ""), "[5] error 메시지 박제")
            async with SessionLocal() as s:
                boom_row = await s.get(BatchRun, _run_ids[-1])
                check(boom_row is not None and boom_row.status == "error", "[5] BatchRun status=error 박제")
        finally:
            JOBS.pop("_v038_boom", None)

        # 미지 작업명 → ValueError
        raised = False
        try:
            await run_job("does-not-exist")
        except ValueError:
            raised = True
        check(raised, "[5] 미지 작업명 → ValueError")

        # mem0 미호출(정적): 세션정리 작업은 memory 모듈을 호출하지 않는다(전사 axis만).
        # 모듈 전체가 아니라 cleanup_sessions 함수 소스만, 그리고 docstring의 산문 언급이 아니라
        # 실제 호출(`memory.` 속성 접근)만 본다 — 같은 모듈의 consolidate_user_memories(스펙 039)는
        # 정당하게 memory를 쓰므로 모듈 단위·산문 단위 검사는 stale.
        import inspect
        clean_src = inspect.getsource(jobs_mod.cleanup_sessions)
        check("memory." not in clean_src and "mem0_memories" not in clean_src,
              "[6] cleanup_sessions가 memory 모듈을 호출하지 않음(정적)")

    finally:
        await _cleanup_db()
        # 원래 설정 복원
        async with SessionLocal() as s:
            cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
            if cfg is not None:
                cfg.session_retention_days = orig_days
                cfg.session_cleanup_cron = orig_cron
                await s.commit()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_038)")


if __name__ == "__main__":
    asyncio.run(main())
