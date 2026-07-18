"""스펙 357 검증 — 삼킨 add 위 파괴적 삭제·거짓 확인 봉합.

`Mem0Backend.add`는 임베더 장애 등을 except로 삼켜 []를 돌린다(by-design graceful). 문제는 그 삼킨
실패를 검사하지 않고 파괴/보고를 진행하는 소비자들이다. 이 테스트는 add를 []로 강제(삼킨 실패 모사)한
뒤, 소비자가 안전한 방향으로 에러하는지 실측한다.

단언:
  C1. 통합 잡: add가 []면 그 유저 원본 **삭제 0** + status="degraded" + failed에 uid + 스냅샷은 박제됨.
  C2. 통합 잡 무회귀: add 성공(비어있지 않음)이면 기존대로 삭제·status="ok"·failed=[].
  C3. 브로커 쓰기(MemoryWriteProvider.invoke): add []면 "저장했습니다" 대신 error(거짓 확인 0).

실 mem0(공유 pgvector)에 검증 유저 기억을 심고 실제 파이프라인을 돈다. LLM 통합(_consolidate)만
결정적 stub. 실 유저 보호: list_memories 게이트로 검증 유저(uid)만 실목록, 그 외 []는 후보 배제.

실행: .venv/bin/python tests/verify_357_swallowed_add.py
"""

import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, func, select  # noqa: E402

from api import memory as memory_mod  # noqa: E402
from api.batch import jobs as jobs_mod  # noqa: E402
from api.batch.runner import run_job  # noqa: E402
from api.broker.providers.memory import MemoryWriteProvider  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402,F401  (모듈 캐시 워밍)
from api.mem_config import default_mem_cfg  # noqa: E402
from api.models import BatchConfig, BatchRun, MemorySnapshot, User  # noqa: E402

SP = "v357-"
THRESHOLD = 3
N = 4

_fails: list[str] = []
_run_ids: list = []
_user_ids: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _set_threshold(value):
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        if cfg is None:
            cfg = BatchConfig()
            s.add(cfg)
        cfg.memory_consolidation_threshold = value
        await s.commit()


def _list(uid, mem_cfg):
    return memory_mod.list_memories({"user_id": uid}, mem_cfg)


def _seed(uid, facts, mem_cfg):
    for f in facts:
        memory_mod.add({"user_id": uid}, [{"role": "user", "content": f}], mem_cfg, False)


async def _snap_count(uid) -> int:
    async with SessionLocal() as s:
        return (
            await s.scalar(
                select(func.count())
                .select_from(MemorySnapshot)
                .where(MemorySnapshot.user_id == uid)
            )
            or 0
        )


async def main() -> None:
    async with SessionLocal() as s:
        mem_cfg = await default_mem_cfg(s)
    if mem_cfg is None:
        print("SKIP: 기본 mem_cfg 미해석(모델 미설정) — 환경 준비 후 재실행")
        return

    async with SessionLocal() as s:
        cfg0 = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        orig_threshold = cfg0.memory_consolidation_threshold if cfg0 else None

    async with SessionLocal() as s:
        u_test = User(email=f"{SP}test@test.local", hashed_password="x")
        s.add(u_test)
        await s.commit()
        await s.refresh(u_test)
        TEST_UID = str(u_test.id)
        _user_ids.append(TEST_UID)

    _real_list = memory_mod.list_memories
    _real_add = memory_mod.add

    def _gated_list(scope, cfg):
        if scope.get("user_id") == TEST_UID:
            return _real_list(scope, cfg)
        return []

    _orig_consolidate = jobs_mod._consolidate
    memory_mod.list_memories = _gated_list

    STUB = ["통합사실 1: 사용자 선호 요약.", "통합사실 2: 사용자 선호 보충."]

    try:
        # seed: 4건(>임계치)
        _seed(TEST_UID, [f"검증사실 {i}: 항목{i} 선호." for i in range(N)], mem_cfg)
        check(len(_list(TEST_UID, mem_cfg)) == N, f"[seed] TEST 유저 기억 {N}건 적재")
        await _set_threshold(THRESHOLD)
        jobs_mod._consolidate = lambda texts, cfg: list(STUB)

        # ── C1: add가 []를 돌리면(삼킨 실패) 삭제 스킵 + degraded ──────────────
        memory_mod.add = lambda *a, **k: []  # 삼킨 add 실패 모사
        snap_before = await _snap_count(TEST_UID)
        r1 = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r1["run_id"])
        memory_mod.add = _real_add  # 즉시 복원(_list/seed가 add에 의존하진 않지만 명확성)
        summ1 = r1.get("summary") or {}
        check(summ1.get("status") == "degraded", "[C1] add 실패 → status=degraded(ok 위장 아님)")
        check(TEST_UID in (summ1.get("failed") or []), "[C1] failed 목록에 uid")
        check(
            TEST_UID not in {c["user_id"] for c in summ1.get("consolidated", [])},
            "[C1] consolidated 미포함(삭제 스킵)",
        )
        check(len(_list(TEST_UID, mem_cfg)) == N, "[C1] 원본 기억 불변(삭제 0 — 유실 방지)")
        # 스냅샷은 삭제 이전에 박제되므로 존재(복구 앵커). 삭제만 안 함.
        check(
            await _snap_count(TEST_UID) == snap_before + N, "[C1] 스냅샷 N행 박제(복구 앵커 존재)"
        )

        # ── C2: add 성공이면 무회귀(삭제 N·ok·failed=[]) ─────────────────────
        # 스냅샷 정리(C1이 남긴 것) 후 재실행.
        async with SessionLocal() as s:
            await s.execute(delete(MemorySnapshot).where(MemorySnapshot.user_id == TEST_UID))
            await s.commit()
        r2 = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r2["run_id"])
        summ2 = r2.get("summary") or {}
        cons = {c["user_id"]: c for c in summ2.get("consolidated", [])}
        check(summ2.get("status") == "ok", "[C2] add 성공 → status=ok")
        check(summ2.get("failed") == [], "[C2] failed 비어있음")
        check(cons.get(TEST_UID, {}).get("deleted") == N, f"[C2] 원본 {N}건 삭제")
        after = _list(TEST_UID, mem_cfg)
        check(
            set(m["text"] for m in after) == set(STUB), "[C2] 최종 기억=통합 stub(적재+삭제 정상)"
        )

        # ── C3: 브로커 쓰기 — add []면 거짓 "저장됨" 대신 error ────────────────
        prov = MemoryWriteProvider(SessionLocal, TEST_UID)
        memory_mod.add = lambda *a, **k: []
        res_fail = await prov.invoke(None, {"text": "저장 시도 사실"})
        memory_mod.add = _real_add
        check(
            res_fail.error is not None and "저장했습니다" not in (res_fail.text or ""),
            "[C3] add [] → error 반환(거짓 '저장됨' 0)",
        )
        # 무회귀: add 성공이면 저장 확인 텍스트.
        memory_mod.add = lambda *a, **k: [{"event": "ADD", "text": "저장 시도 사실"}]
        res_ok = await prov.invoke(None, {"text": "저장 시도 사실"})
        memory_mod.add = _real_add
        check(
            res_ok.error is None and "저장했습니다" in (res_ok.text or ""),
            "[C3] add 성공 → '저장했습니다' 확인(무회귀)",
        )

    finally:
        jobs_mod._consolidate = _orig_consolidate
        memory_mod.list_memories = _real_list
        memory_mod.add = _real_add
        for uid in _user_ids:
            for m in _real_list({"user_id": uid}, mem_cfg):
                memory_mod.delete_memory(m["id"], mem_cfg)
        async with SessionLocal() as s:
            await s.execute(delete(MemorySnapshot).where(MemorySnapshot.user_id.in_(_user_ids)))
            if _run_ids:
                await s.execute(
                    delete(BatchRun).where(BatchRun.id.in_([uuid.UUID(r) for r in _run_ids]))
                )
            await s.execute(delete(User).where(User.id.in_([uuid.UUID(u) for u in _user_ids])))
            await s.commit()
        await _set_threshold(orig_threshold)

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_357)")


if __name__ == "__main__":
    asyncio.run(main())
