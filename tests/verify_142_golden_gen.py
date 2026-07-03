"""verify_142 — 골든셋 자동 생성 (스펙 142).

  G1 _parse_question 단위: 유효 질문·물음표 없음·짧음·문단 지칭·빈 응답 거부.
  G2 GenerateIn 범위: count 0/21 → 스키마 거부.
  G3 실 생성(Obsidian, count 3): 케이스 ≥2건(형식 이탈 여유)·자기일관 기준 3종 자동 부여·
     description에 결과 박제.
  G4 self-consistency: 생성 문제집을 그 컬렉션으로 실행 → 통과율 ≥ 2/3(생성 질문이 출처를 되찾는가).
실행: uv run --project packages/api python tests/verify_142_golden_gen.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import eval_routes as ER  # noqa: E402
from api.eval_golden import _parse_question  # noqa: E402
from api.models import Collection, EvalCase, EvalDataset, EvalRun  # noqa: E402  # noqa: F401
from api.rag import resolve_search_collection  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)

class _Super:
    id = _uuid.uuid4()
    is_superuser = True
    email = "verify142@example.com"

def part_g12():
    check(_parse_question("A/B 테스트에서 문해력이 중요한 이유는 무엇인가?") is not None, "G1a 유효 질문")
    check(_parse_question("문해력이 중요하다") is None, "G1b 물음표 없음 → None")
    check(_parse_question("왜?") is None, "G1c 5자 미만 → None")
    check(_parse_question("이 문단에서 말하는 핵심은?") is None, "G1d 문단 지칭 → None")
    check(_parse_question("") is None and _parse_question("  \n ") is None, "G1e 빈 응답 → None")
    check(_parse_question('"질문은 따옴표를 벗는가?"') == "질문은 따옴표를 벗는가?", "G1f 따옴표 스트립")
    check(_parse_question("A/B 테스트에서 문해력이 중요한 이유는 무엇인가") == "A/B 테스트에서 문해력이 중요한 이유는 무엇인가?",
          "G1g 의문형 어미 정규화(e2e 실측 — 물음표 자동 부여)")
    check(_parse_question("문해력이 가장 중요한 요소이다") is None, "G1h 평서문은 여전히 거부")
    for bad in (0, 21):
        try:
            ER.GenerateIn(collection_id=_uuid.uuid4(), name="x", count=bad)
            check(False, f"G2 count={bad} → 거부여야")
        except ValidationError:
            check(True, f"G2 count={bad} → 스키마 거부")

async def main():
    part_g12()
    sup = _Super()
    tag = f"v142-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        col_row = (await s.execute(select(Collection).where(Collection.name == "Obsidian"))).scalar_one_or_none()
        if col_row is None:
            check(False, "전제 실패: Obsidian 컬렉션 없음"); sys.exit(1)
        col = await resolve_search_collection(s, col_row.id)
    # G3 — 생성(백그라운드 없이 직접 실행: 결정적)
    async with async_session() as s:
        ds = EvalDataset(name=f"{tag}-골든", description="생성 중…", kind="rag")
        s.add(ds); await s.commit(); ds_id = ds.id
    try:
        await ER._execute_generation(ds_id, col_row.id, 3)
        async with async_session() as s:
            ds2 = await s.get(EvalDataset, ds_id)
            cases = (await s.execute(select(EvalCase).where(EvalCase.dataset_id == ds_id))).scalars().all()
        check(len(cases) >= 2, f"G3a 케이스 {len(cases)}건(요청 3, ≥2 허용 — 형식 이탈 여유)")
        ok_asserts = all(
            {a["type"] for a in c.asserts} == {"rag_source_contains", "rag_hits_gte", "no_error"}
            and c.input.endswith("?")
            for c in cases
        )
        check(ok_asserts, "G3b 자기일관 기준 3종+질문 형식")
        check(ds2.description.startswith("자동 생성"), f"G3c description 박제 ({ds2.description[:40]!r})")
        # G4 — self-consistency 실행
        async with async_session() as s:
            run_row = EvalRun(dataset_id=ds_id, agent_name="RAG · Obsidian", status="running",
                              total=len(cases))
            s.add(run_row); await s.commit(); run_id = run_row.id
        await ER._execute_run(run_id, ds_id, None, sup, rag_collection=col)
        async with async_session() as s:
            run = await s.get(EvalRun, run_id)
        check(run.status == "ok" and run.score is not None and run.score >= 2 / 3,
              f"G4 self-consistency ≥ 2/3 (got {run.score}, {run.passed}/{run.total})")
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds_id, session=s, user=sup)
            except Exception:
                pass

    # G5(codex 핀) — 생성 중 실행 게이트 + 좀비 sweep + 빈 생성 실패 박제
    async with async_session() as s:
        z = EvalDataset(name=f"{tag}-좀비생성", description="생성 중… (문제가 곧 채워집니다)", kind="rag")
        s.add(z); await s.commit(); zid = z.id
    try:
        from fastapi import HTTPException as _HTTPExc
        async with async_session() as s:
            try:
                await ER.start_run(zid, ER.RunStartIn(collection_id=col_row.id), session=s, user=sup)
                check(False, "G5a 생성 중 실행 → 409여야")
            except _HTTPExc as e:
                check(e.status_code == 409, f"G5a 생성 중 실행 게이트 409 (got {e.status_code})")
        n = await ER.sweep_zombie_datasets()
        async with async_session() as s:
            z2 = await s.get(EvalDataset, zid)
        check(n >= 1 and z2.description.startswith("생성 중단"), f"G5b 좀비 생성 sweep 박제 ({z2.description[:20]!r})")
        # 빈 생성 실패 박제 — 존재하지 않는 컬렉션 id로 생성 실행(후보 0)
        async with async_session() as s:
            e0 = EvalDataset(name=f"{tag}-빈생성", description="생성 중…", kind="rag")
            s.add(e0); await s.commit(); e0id = e0.id
        await ER._execute_generation(e0id, _uuid.uuid4(), 3)
        async with async_session() as s:
            e02 = await s.get(EvalDataset, e0id)
        check("생성 실패" in (e02.description or ""), f"G5c 빈 생성=실패 박제 ({e02.description[:30]!r})")
        async with async_session() as s:
            try: await ER.delete_dataset(e0id, session=s, user=sup)
            except Exception: pass
    finally:
        async with async_session() as s:
            try: await ER.delete_dataset(zid, session=s, user=sup)
            except Exception: pass

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails: sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
