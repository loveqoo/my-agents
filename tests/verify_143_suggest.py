"""verify_143 — 에이전트 문제집 AI 출제 (스펙 143).

  S1 mock 판별: /_remote 주소·mock 접두 → True, 실모델 → False.
  S2 게이트: rag 문제집 400·미존재 에이전트 404·count 0/11 스키마 거부.
  S3 도우미 게이트(스펙 402 재활): 기본 chat이 mock이면 도우미 불가+사유 문자열(제품 원칙 —
     eval_guards._helper_llm)을 **단언**한다. 실모델 전체 출제 경로(구 S3/S4 — RAG형+역할형 혼합·
     자기일관 ≥1/2)는 외부 모델 서버 가용성에 묶여 그물에 못 넣으므로 VERIFY_143_FULL=1
     opt-in일 때만 실행(에이전트는 자기완결 생성 — 구 옵시디언 매니저 시드 전제 제거).
  S5 좀비 sweep 확장: "AI 출제 중…" 잔류 → 중단 박제. S5' 진행 락 409.
실행: uv run --project packages/api python tests/verify_143_suggest.py
"""

import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import eval_routes as ER  # noqa: E402
from api.eval_harness import build_asserts  # noqa: E402
from api.eval_suggest import is_mock_llm  # noqa: E402
from api.models import Agent, EvalCase, EvalDataset, EvalRun  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _Super:
    id = _uuid.uuid4()
    is_superuser = True
    email = "verify143@example.com"


async def main():
    sup = _Super()
    tag = f"v143-{_uuid.uuid4().hex[:6]}"
    # S1
    check(
        is_mock_llm("http://127.0.0.1:8000/_remote/v1", "mock-chat") is True, "S1a 내장 mock → True"
    )
    check(is_mock_llm("http://x/v1", "Mocked-3b") is True, "S1b mock 접두 → True")
    check(
        is_mock_llm("http://localhost:8045/v1", "mlx-community/Qwen3.6") is False,
        "S1c 실모델 → False",
    )
    check(
        is_mock_llm("https://api.example.com/_remote/v1", "gpt-4o") is False,
        "S1d 외부 URL의 /_remote는 오탐 아님(codex 143 — 로컬 호스트 결합 판정)",
    )
    # S2
    for bad in (0, 11):
        try:
            ER.SuggestIn(agent_id=_uuid.uuid4(), count=bad)
            check(False, f"S2a count={bad} 거부여야")
        except ValidationError:
            check(True, f"S2a count={bad} → 스키마 거부")
    # 자기완결 픽스처(스펙 402) — 구 옵시디언 매니저 시드 전제 제거. 게이트 축(S2b·S5')에 필요한
    # 에이전트를 직접 만든다(RAG 배선 포함 — opt-in 전체 출제 경로에서도 재사용).
    async with async_session() as s:
        agent = Agent(
            agent_id=f"agt_{tag}",
            name=f"{tag}-agent",
            source="ui",
            prompt="문서를 검색해 근거로 답하는 지식 도우미.",
            config={"vectorTables": ["docs-kb"]},
            active_version="v1",
        )
        s.add(agent)
        await s.commit()
        await s.refresh(agent)
    async with async_session() as s:
        ds_rag = await ER.create_dataset(
            ER.DatasetIn(name=f"{tag}-rag", kind="rag"), session=s, user=sup
        )
    try:
        async with async_session() as s:
            try:
                await ER.suggest_cases(
                    ds_rag.id, ER.SuggestIn(agent_id=agent.id, count=2), session=s, user=sup
                )
                check(False, "S2b rag 문제집 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"S2b rag 문제집 400 (got {e.status_code})")
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds_rag.id, session=s, user=sup)
            except Exception:
                pass

    # S3 — 도우미 게이트 단언(가용성은 제품 원칙: 기본 chat이 실모델일 때만).
    async with async_session() as s:
        llm, reason = await ER._helper_llm(s)
    if llm is None:
        check(
            reason is not None and "mock" in reason,
            f"S3-gate 기본 chat=mock → 도우미 불가+사유 명시 (got {reason!r})",
        )
    else:
        check(True, "S3-gate 기본 chat=실모델 → 도우미 가용")
    if llm is None or not os.environ.get("VERIFY_143_FULL"):
        # 전체 출제 경로는 실모델(외부 서버 가용) 전제 — opt-in에서만. 게이트·락·sweep 축으로 종료.
        print("  (skip) S3/S4 전체 출제 경로 — 실모델+VERIFY_143_FULL=1 에서만 실행")
        await _lock_and_sweep(tag, sup, agent)
        await _cleanup_agent(agent.id)
        print(f"\n{passed} passed, {len(_fails)} failed")
        if _fails:
            sys.exit(1)
        return

    # (opt-in) 실 출제 — 기존 문제 1개 심어 보존 확인.
    async with async_session() as s:
        ds = await ER.create_dataset(
            ER.DatasetIn(name=f"{tag}-출제", description="원본 설명"), session=s, user=sup
        )
    try:
        async with async_session() as s:
            await ER.create_case(
                ds.id,
                ER.CaseIn(
                    name="사람이 쓴 문제",
                    input="수동 질문?",
                    asserts=[{"type": "no_error"}],
                    order_idx=0,
                ),
                session=s,
                user=sup,
            )
        await ER._execute_suggestion(ds.id, agent.id, 4, llm, "원본 설명")
        async with async_session() as s:
            ds2 = await s.get(EvalDataset, ds.id)
            cases = (
                (
                    await s.execute(
                        select(EvalCase)
                        .where(EvalCase.dataset_id == ds.id)
                        .order_by(EvalCase.order_idx)
                    )
                )
                .scalars()
                .all()
            )
        ai_cases = [c for c in cases if c.name.startswith("AI 출제")]
        check(
            cases[0].name == "사람이 쓴 문제" and len(ai_cases) >= 3,
            f"S3b 기존 보존+AI {len(ai_cases)}건 추가(요청 4, ≥3 허용)",
        )
        has_rag = any(
            "(RAG)" in c.name and any(a["type"] == "trace_has" for a in c.asserts) for c in ai_cases
        )
        has_prompt = any(
            "(역할)" in c.name and any(a["type"] == "llm_judge" for a in c.asserts)
            for c in ai_cases
        )
        check(has_rag and has_prompt, f"S3c RAG형+역할형 혼합 (rag={has_rag}, prompt={has_prompt})")
        ok_asserts = all(build_asserts(c.asserts) for c in ai_cases)
        check(
            ok_asserts and all(c.input.endswith("?") for c in ai_cases),
            "S3d 전건 build_asserts 통과+질문 형식",
        )
        check(
            ds2.description.startswith("원본 설명 · AI 출제") and "건 추가" in ds2.description,
            f"S3e description 박제 ({ds2.description[:40]!r})",
        )
        # S4 — 자기일관 실행
        async with async_session() as s:
            run_row = EvalRun(
                dataset_id=ds.id,
                agent_pk=agent.id,
                agent_name=agent.name,
                status="running",
                total=len(cases),
            )
            s.add(run_row)
            await s.commit()
            run_id = run_row.id
        await ER._execute_run(run_id, ds.id, agent.id, sup)
        async with async_session() as s:
            run = await s.get(EvalRun, run_id)
        check(
            run.status == "ok" and run.score is not None and run.score >= 0.5,
            f"S4 자기일관 ≥ 1/2 (got {run.score}, {run.passed}/{run.total})",
        )
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds.id, session=s, user=sup)
            except Exception:
                pass

    await _lock_and_sweep(tag, sup, agent)
    await _cleanup_agent(agent.id)

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)
    return


async def _cleanup_agent(agent_pk):
    async with async_session() as s:
        row = await s.get(Agent, agent_pk)
        if row:
            await s.delete(row)
            await s.commit()


async def _lock_and_sweep(tag, sup, agent):
    # S5' — 진행 락 게이트(codex 143: description 아닌 메모리 락 — PATCH 우회 불가)
    async with async_session() as s:
        ds_lock = await ER.create_dataset(ER.DatasetIn(name=f"{tag}-락"), session=s, user=sup)
    try:
        ER._active_jobs.add(ds_lock.id)
        async with async_session() as s:
            try:
                await ER.suggest_cases(
                    ds_lock.id, ER.SuggestIn(agent_id=agent.id, count=2), session=s, user=sup
                )
                check(False, "S5' 락 중 재출제 → 409여야")
            except HTTPException as e:
                check(e.status_code == 409, f"S5' 진행 락 409 (got {e.status_code})")
    finally:
        ER._active_jobs.discard(ds_lock.id)
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds_lock.id, session=s, user=sup)
            except Exception:
                pass

    # S5 — sweep 확장
    async with async_session() as s:
        z = EvalDataset(name=f"{tag}-좀비출제", description="원본 · AI 출제 중…", kind="agent")
        s.add(z)
        await s.commit()
        zid = z.id
    try:
        n = await ER.sweep_zombie_datasets()
        async with async_session() as s:
            z2 = await s.get(EvalDataset, zid)
        check(
            n >= 1 and "AI 출제 중단" in (z2.description or ""),
            f"S5 출제 좀비 sweep ({z2.description[:40]!r})",
        )
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(zid, session=s, user=sup)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
