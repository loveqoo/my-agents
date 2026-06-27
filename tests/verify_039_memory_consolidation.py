"""스펙 039 검증 — 유저 장기기억(user_id 축) 통합·재적재 배치.

`api.batch.jobs.consolidate_user_memories`를 인프로세스로 단언한다. 실 mem0(공유 pgvector)에
검증 유저의 기억을 심고 실제 add/snapshot/delete 파이프라인을 돌린다. LLM 통합 단계(`_consolidate`)만
결정적 stub으로 monkeypatch해 검증을 빠르고 재현 가능하게 한다(타사 LLM 응답에 의존하지 않음).

**실 유저 보호**: 작업은 User 테이블 전원을 스캔하므로, `memory.list_memories`를 게이트로 패치해
검증 유저(v039_ prefix uid)만 실제 목록을, 그 외 유저는 []를 돌려준다 → 실 유저는 후보가 되지
않아 그들의 mem0 기억을 절대 건드리지 않는다. add/delete는 후보(검증 유저)에만 실행된다.

단언:
  seed. 검증 유저에 N개 기억 적재(>임계치).
  1. dry-run은 무변형: candidates 미리보기만, 기억수·스냅샷 불변 + 감사행 summary에 sample 미영속(재귀 scrub).
  2. 실행: 원본 N건 MemorySnapshot 박제(run_id 링크) → 통합본 적재 → 박제한 mem_id만 삭제. 0<after<N.
  3. 비활성: threshold NULL/<2 → disabled + 무변형.
  4. 안전 불변식 2: 통합 결과가 비면 그 유저 전체 스킵(스냅샷·삭제 0).
  5. mem_cfg 미해석 → disabled(no_mem_cfg).
  6. 임계치 미달 타 유저는 불변(per-user 게이팅).

실행: .venv/bin/python tests/verify_039_memory_consolidation.py
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
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402,F401  (모듈 캐시 워밍)
from api.mem_config import default_mem_cfg  # noqa: E402
from api.models import BatchConfig, BatchRun, MemorySnapshot, User  # noqa: E402

SP = "v039-"  # 검증 유저 email prefix
THRESHOLD = 3  # N=4 > 3 → 후보. 미달 유저(2건)는 비후보.
N = 4

_fails: list[str] = []
_run_ids: list = []
_user_ids: list[str] = []  # 검증 유저 uid(=str(user.id)) — 게이트·정리에 사용


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ── BatchConfig 싱글톤(앱과 공유 1행) 저장/복원/설정 ──────────────────────────
async def _set_threshold(value):
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        if cfg is None:
            cfg = BatchConfig()
            s.add(cfg)
        cfg.memory_consolidation_threshold = value
        await s.commit()


# ── mem0 헬퍼(실 저장소, 검증 유저 한정) ─────────────────────────────────────
def _list(uid, mem_cfg):
    return memory_mod.list_memories({"user_id": uid}, mem_cfg)


def _seed(uid, facts, mem_cfg):
    """검증 유저에 사실들을 verbatim 적재(infer=False — 재추출로 모양 안 바뀌게)."""
    for f in facts:
        memory_mod.add({"user_id": uid}, [{"role": "user", "content": f}], mem_cfg, False)


async def _snap_count(uid) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).select_from(MemorySnapshot).where(MemorySnapshot.user_id == uid)
        ) or 0


async def main() -> None:
    async with SessionLocal() as s:
        mem_cfg = await default_mem_cfg(s)
    if mem_cfg is None:
        print("SKIP: 기본 mem_cfg 미해석(모델 미설정) — 환경 준비 후 재실행")
        return

    # 원래 임계치 저장(복원용)
    async with SessionLocal() as s:
        cfg0 = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        orig_threshold = cfg0.memory_consolidation_threshold if cfg0 else None

    # 검증 유저 2명 생성: TEST(후보, N건), OTHER(미달, 2건)
    async with SessionLocal() as s:
        u_test = User(email=f"{SP}test@test.local", hashed_password="x")
        u_other = User(email=f"{SP}other@test.local", hashed_password="x")
        s.add_all([u_test, u_other])
        await s.commit()
        await s.refresh(u_test)
        await s.refresh(u_other)
        TEST_UID, OTHER_UID = str(u_test.id), str(u_other.id)
        _user_ids.extend([TEST_UID, OTHER_UID])

    # list_memories 게이트 — 검증 유저만 실 목록, 그 외 유저는 [](실 유저 보호).
    _real_list = memory_mod.list_memories

    def _gated_list(scope, cfg):
        if scope.get("user_id") in (TEST_UID, OTHER_UID):
            return _real_list(scope, cfg)
        return []

    _orig_consolidate = jobs_mod._consolidate
    _orig_default = jobs_mod.default_mem_cfg
    memory_mod.list_memories = _gated_list  # jobs_mod.memory 는 같은 모듈 객체

    try:
        # seed: TEST=4건(>임계치), OTHER=2건(미달)
        _seed(TEST_UID, [f"검증사실 {i}: 사용자는 항목{i}를 선호한다." for i in range(N)], mem_cfg)
        _seed(OTHER_UID, ["타유저 사실 A", "타유저 사실 B"], mem_cfg)
        check(len(_list(TEST_UID, mem_cfg)) == N, f"[seed] TEST 유저 기억 {N}건 적재")
        check(len(_list(OTHER_UID, mem_cfg)) == 2, "[seed] OTHER 유저 기억 2건 적재(미달)")

        await _set_threshold(THRESHOLD)

        # 결정적 stub: N건 → 2건으로 통합
        STUB = ["통합사실 1: 사용자 선호 요약.", "통합사실 2: 사용자 선호 보충."]
        jobs_mod._consolidate = lambda texts, cfg: list(STUB)

        # ── [1] dry-run: 무변형 + 미리보기 ────────────────────────────────
        r1 = await run_job("memory-consolidation", dry_run=True)
        _run_ids.append(r1["run_id"])
        summ1 = r1.get("summary") or {}
        cand1 = {c["user_id"]: c for c in summ1.get("candidates", [])}
        check(summ1.get("status") == "dry_run", "[1] dry-run status=dry_run")
        check(TEST_UID in cand1, "[1] TEST 유저가 후보로 집계")
        check(OTHER_UID not in cand1, "[1] OTHER 유저(미달)는 후보 아님")
        check(
            cand1.get(TEST_UID, {}).get("before") == N and cand1.get(TEST_UID, {}).get("after") == len(STUB),
            f"[1] 미리보기 before={N} after={len(STUB)}",
        )
        check(len(_list(TEST_UID, mem_cfg)) == N, "[1] dry-run 후 기억수 불변(무변형)")
        check(await _snap_count(TEST_UID) == 0, "[1] dry-run 후 스냅샷 0(무변형)")
        # 감사행 scrub: BatchRun.summary.candidates 에 sample 키가 없어야(재귀 scrub)
        async with SessionLocal() as s:
            row1 = await s.get(BatchRun, r1["run_id"])
        audit_cands = (row1.summary or {}).get("candidates", []) if row1 else []
        check(
            bool(audit_cands) and all("sample" not in c for c in audit_cands),
            "[1] 감사행 summary.candidates 에 sample 미영속(재귀 scrub)",
        )
        # 라이브 응답에는 sample 보존(미리보기 가치)
        check("sample" in cand1.get(TEST_UID, {}), "[1] 라이브 응답엔 sample 보존")

        # ── [2] 실행: 스냅샷→적재→삭제 ────────────────────────────────────
        r2 = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r2["run_id"])
        summ2 = r2.get("summary") or {}
        cons = {c["user_id"]: c for c in summ2.get("consolidated", [])}
        check(summ2.get("status") == "ok", "[2] 실행 status=ok")
        check(TEST_UID in cons, "[2] TEST 유저 통합 수행")
        c = cons.get(TEST_UID, {})
        check(
            c.get("before") == N and c.get("after") == len(STUB) and c.get("snapshot") == N and c.get("deleted") == N,
            f"[2] before={N} after={len(STUB)} snapshot={N} deleted={N}",
        )
        check(summ2.get("total_before") == N and summ2.get("total_after") == len(STUB), "[2] 합계 before/after")
        # MemorySnapshot: N행 + run_id 링크
        async with SessionLocal() as s:
            snaps = (await s.execute(select(MemorySnapshot).where(MemorySnapshot.user_id == TEST_UID))).scalars().all()
        check(len(snaps) == N, f"[2] MemorySnapshot {N}행 박제")
        check(all(str(sn.batch_run_id) == r2["run_id"] for sn in snaps), "[2] 스냅샷 batch_run_id=run_id 링크")
        # 원본 삭제 + 통합본 적재 → 최종 기억수 == len(STUB).
        # ISSUE 4 핀: deleted==N(원본 N개가 add 이후에도 살아 있어 명시 삭제로 지워짐) + 최종==STUB은
        # mem0 add(infer=False)가 형제 기억을 건드리지 않는 순수 insert임을 실측으로 증명한다.
        after = _list(TEST_UID, mem_cfg)
        check(len(after) == len(STUB), f"[2] 최종 기억수 {len(STUB)}(원본 삭제+통합본 적재)")
        check(0 < len(after) < N, "[2] 0 < after < before(압축됨)")
        after_texts = {m["text"] for m in after}
        check(after_texts == set(STUB), "[2] 최종 기억 본문 == 통합 stub")

        # ── [6] OTHER 유저(미달)는 불변 ──────────────────────────────────
        check(len(_list(OTHER_UID, mem_cfg)) == 2, "[6] OTHER 유저(미달) 기억 불변")
        check(await _snap_count(OTHER_UID) == 0, "[6] OTHER 유저 스냅샷 없음")

        # ── [3] 비활성: threshold NULL / <2 ──────────────────────────────
        await _set_threshold(None)
        r3 = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r3["run_id"])
        check((r3.get("summary") or {}).get("status") == "disabled", "[3] threshold=NULL → disabled")
        await _set_threshold(1)  # API ge=2지만 작업 가드(<2)를 직접 단언
        r3b = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r3b["run_id"])
        check((r3b.get("summary") or {}).get("status") == "disabled", "[3] threshold=1(<2) → disabled")

        # ── [4] 안전 불변식 2: 통합 빈 결과 → 유저 전체 스킵 ───────────────
        # TEST를 다시 후보로(현재 2건 → 2건 추가해 4건). 임계치 3.
        _seed(TEST_UID, ["추가사실 X", "추가사실 Y"], mem_cfg)
        check(len(_list(TEST_UID, mem_cfg)) == N, "[4] TEST 재적재 4건(>임계치)")
        await _set_threshold(THRESHOLD)
        snap_before = await _snap_count(TEST_UID)
        jobs_mod._consolidate = lambda texts, cfg: []  # 빈 결과 → 삭제 차단
        r4 = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r4["run_id"])
        check((r4.get("summary") or {}).get("status") == "ok", "[4] 실행 status=ok")
        check(
            TEST_UID not in {c["user_id"] for c in (r4.get("summary") or {}).get("consolidated", [])},
            "[4] 통합 빈 결과 → consolidated 미포함(스킵)",
        )
        check(len(_list(TEST_UID, mem_cfg)) == N, "[4] 기억 불변(삭제 안 함 — 안전 불변식 2)")
        check(await _snap_count(TEST_UID) == snap_before, "[4] 스냅샷 추가 없음(삭제 안 했으므로)")

        # ── [4b] 안전 floor: 비지 않아도 '미축소'면 스킵(쓰레기 출력 방어, _valid_consolidation) ─
        # 원본 N건 → N건(거부문/원문 에코를 흉내) 반환: 줄지 않으므로 파괴적 교체 금지.
        jobs_mod._consolidate = lambda texts, cfg: [f"미축소 {i}" for i in range(N)]
        snap_before_4b = await _snap_count(TEST_UID)
        r4b = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r4b["run_id"])
        check(
            TEST_UID not in {c["user_id"] for c in (r4b.get("summary") or {}).get("consolidated", [])},
            "[4b] 미축소(N→N) → consolidated 미포함(스킵)",
        )
        check(len(_list(TEST_UID, mem_cfg)) == N, "[4b] 기억 불변(미축소면 삭제 안 함)")
        check(await _snap_count(TEST_UID) == snap_before_4b, "[4b] 스냅샷 추가 없음")
        # dry-run 미리보기는 이 스킵을 정직히 표기(skip='no_shrink')
        r4c = await run_job("memory-consolidation", dry_run=True)
        _run_ids.append(r4c["run_id"])
        cand4c = {c["user_id"]: c for c in (r4c.get("summary") or {}).get("candidates", [])}
        check(cand4c.get(TEST_UID, {}).get("skip") == "no_shrink", "[4b] dry-run이 skip='no_shrink' 표기")

        # ── [5] mem_cfg 미해석 → disabled(no_mem_cfg) ────────────────────
        async def _none(_s):
            return None

        jobs_mod.default_mem_cfg = _none
        r5 = await run_job("memory-consolidation", dry_run=False)
        _run_ids.append(r5["run_id"])
        summ5 = r5.get("summary") or {}
        check(
            summ5.get("status") == "disabled" and summ5.get("reason") == "no_mem_cfg",
            "[5] mem_cfg 미해석 → disabled(no_mem_cfg)",
        )

    finally:
        # 복원
        jobs_mod._consolidate = _orig_consolidate
        jobs_mod.default_mem_cfg = _orig_default
        memory_mod.list_memories = _real_list
        # mem0 정리 — 검증 유저 기억 전삭제
        for uid in _user_ids:
            for m in _real_list({"user_id": uid}, mem_cfg):
                memory_mod.delete_memory(m["id"], mem_cfg)
        # DB 정리 — 스냅샷·BatchRun·User
        async with SessionLocal() as s:
            await s.execute(delete(MemorySnapshot).where(MemorySnapshot.user_id.in_(_user_ids)))
            if _run_ids:
                await s.execute(delete(BatchRun).where(BatchRun.id.in_([uuid.UUID(r) for r in _run_ids])))
            await s.execute(delete(User).where(User.id.in_([uuid.UUID(u) for u in _user_ids])))
            await s.commit()
        # 임계치 복원
        await _set_threshold(orig_threshold)

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_039)")


if __name__ == "__main__":
    asyncio.run(main())
