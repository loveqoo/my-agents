"""verify_140 — RAG 컬렉션 평가 러너 (스펙 140).

  R1 assert 3종 매핑·arg 형식 오류 거부(비정수/비실수)·fail-closed(obs["rag"] 부재=False).
  R2 실 컬렉션 통합(Obsidian): "A/B 테스트" 질의 → hits>0·top_score 실수·output에 결과 본문,
     rag_source_contains(실제 근거 파일)·rag_score_gte 채점 통과.
  R3 실행 분기: rag 문제집 + collection_id로 _execute_run → status=ok·결과 영속(obs.rag 포함).
     agent 문제집에 rag assert → False(전용 기준의 정직한 실패).
실행: uv run --project packages/api python tests/verify_140_rag_eval.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import eval_routes as ER  # noqa: E402
from api.eval_harness import build_asserts, rag_hits_gte, rag_score_gte, rag_source_contains  # noqa: E402
from api.eval_runner import eval_run_rag  # noqa: E402
from api.models import Collection, EvalCaseResult, EvalRun  # noqa: E402
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
    email = "verify140@example.com"

def part_r1():
    sc = build_asserts([{"type": "rag_hits_gte", "arg": "2"}, {"type": "rag_score_gte", "arg": "0.4"},
                        {"type": "rag_source_contains", "arg": "노트"}])
    check(len(sc) == 3, "R1a 3종 매핑")
    for bad, label in [([{"type": "rag_hits_gte", "arg": "둘"}], "비정수"),
                       ([{"type": "rag_score_gte", "arg": "높게"}], "비실수")]:
        try:
            build_asserts(bad); check(False, f"R1b {label} → ValueError여야")
        except ValueError:
            check(True, f"R1b {label} arg → ValueError")
    agent_obs = {"output": "답", "trace_nodes": ["analyze"], "error": False}  # rag 없음
    check(rag_hits_gte("1")[1](agent_obs) is False and rag_score_gte("0.1")[1](agent_obs) is False
          and rag_source_contains("x")[1](agent_obs) is False,
          "R1c obs.rag 부재(agent 런) → 전부 False(fail-closed)")

async def main():
    part_r1()
    async with async_session() as s:
        vt = (await s.execute(select(Collection).where(Collection.name == "Obsidian"))).scalar_one_or_none()
        if vt is None:
            check(False, "전제 실패: Obsidian 컬렉션 없음"); sys.exit(1)
        col = await resolve_search_collection(s, vt.id)
        col_id = vt.id

    obs = await eval_run_rag(col, "A/B 테스트에서 중요한 것은?")
    check(not obs["error"] and len(obs["rag"]["hits"]) > 0,
          f"R2a 검색 성공·hits {len(obs['rag']['hits'])}건")
    check(isinstance(obs["rag"]["top_score"], float) and "문서 검색 결과" in obs["output"],
          f"R2b top_score={obs['rag'].get('top_score')}·output 본문")
    src = obs["rag"]["hits"][0]["filename"]
    check(rag_source_contains(src[:6])[1](obs) is True, f"R2c source_contains({src[:6]!r}) 통과")
    check(rag_score_gte(str(round(obs['rag']['top_score'] - 0.05, 2)))[1](obs) is True, "R2d score_gte 통과")
    check(rag_hits_gte("100")[1](obs) is False, "R2e hits_gte 100 → False(경계)")

    # R3 실행 분기 파이프라인
    sup = _Super()
    tag = f"v140-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        ds = await ER.create_dataset(ER.DatasetIn(name=f"{tag}-rag시험", kind="rag"), session=s, user=sup)
    try:
        async with async_session() as s:
            await ER.create_case(ds.id, ER.CaseIn(
                name="검색 회귀", input="A/B 테스트에서 중요한 것은?",
                asserts=[{"type": "rag_hits_gte", "arg": "1"}, {"type": "no_error"},
                         {"type": "rag_source_contains", "arg": src[:6]}]), session=s, user=sup)
        async with async_session() as s:
            run_row = EvalRun(dataset_id=ds.id, agent_name="RAG · Obsidian", status="running", total=1)
            s.add(run_row); await s.commit(); run_id = run_row.id
        await ER._execute_run(run_id, ds.id, None, sup, rag_collection=col)
        async with async_session() as s:
            run = await s.get(EvalRun, run_id)
            check(run.status == "ok" and run.score == 1.0, f"R3a rag run ok·1.0 (got {run.status}, {run.score})")
            res = (await s.execute(select(EvalCaseResult).where(EvalCaseResult.run_id == run_id))).scalars().all()
            check(res and res[0].obs.get("rag", {}).get("hits"), "R3b obs.rag 영속(근거 파일·score)")
    finally:
        async with async_session() as s:
            try: await ER.delete_dataset(ds.id, session=s, user=sup)
            except Exception: pass

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails: sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
