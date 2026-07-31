"""평가 실행 코어(배경 러너) — eval_runs.py에서 분할(스펙 399 P6).

상태 commit 순서 동결(codex 399): running(생성 시) → case_results insert → ok/error+finished_at
commit. _execute_run(구 B10)은 케이스 로딩(_load_harness_cases)·judge 해석(_resolve_judge_llm)·
결과 영속(_persist_report)·오류 박제(_mark_run_error) 추출로 분해. 파사드는 eval_runs.py(재수출).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from . import events
from .db import SessionLocal
from .eval_harness import EvalCase as HarnessCase
from .eval_harness import build_asserts, run_eval
from .eval_runner import eval_run_agent
from .models import EvalCase, EvalCaseResult, EvalDataset, EvalRun, User


async def _load_harness_cases(dataset_id: uuid.UUID) -> list[HarnessCase]:
    """문제집 케이스 → 하네스 케이스(순서 보존). 스펙 195: 성적표 식별자(case_name)에 **질문**을
    넣는다 — DB name은 내부 해시라 성적표에 뜨면 유저가 못 알아본다. 표시 상한 200자."""
    async with SessionLocal() as s:
        rows = (
            (
                await s.execute(
                    select(EvalCase)
                    .where(EvalCase.dataset_id == dataset_id)
                    .order_by(EvalCase.order_idx, EvalCase.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [
            HarnessCase(
                name=(c.input or c.name)[:200],
                input=c.input,
                asserts=build_asserts(c.asserts),
                meta={"raw_asserts": c.asserts},
            )
            for c in rows
        ]


async def _resolve_judge_llm() -> dict | None:
    """LLM-judge 심판 모델(스펙 139) — 기본 chat 모델(is_default)만 직접 해석. default_mem_cfg는
    embedding까지 요구해 embedding 미설정이 judge를 인질로 잡는다(codex 139 #3) → chat만 본다.
    미설정이면 judge 전부 실패(fail-closed) — run_llm_judge가 사유를 남긴다."""
    from .mem_config import _default_chat_model, llm_cfg_of, model_usable

    async with SessionLocal() as s:
        _cm = await _default_chat_model(s)
    return llm_cfg_of(_cm) if model_usable(_cm) else None


async def _persist_report(run_id: uuid.UUID, report) -> None:  # noqa: ANN001 — EvalReport(하네스 타입)
    """성적 영속 — case_results insert 후 run을 ok로 종결(+finished_at). 순서 동결(codex 399)."""
    async with SessionLocal() as s:
        run = await s.get(EvalRun, run_id)
        if run is None:
            return
        for result in report.results:
            s.add(
                EvalCaseResult(
                    run_id=run_id,
                    case_name=result.name,
                    case_passed=result.passed,
                    details=[list(d) for d in result.details],
                    obs=result.obs,
                )
            )
        run.status = "ok"
        run.score = report.score
        run.passed = report.passed
        run.total = report.total
        run.summary = {"summary": report.summary()}
        run.finished_at = datetime.now(UTC)
        # 알림용 dataset 이름 박제(스펙 436) — 세션 밖 ORM 금지(스펙 434 교훈), 커밋 전에 스칼라로.
        _ds_name = (
            await s.execute(select(EvalDataset.name).where(EvalDataset.id == run.dataset_id))
        ).scalar_one_or_none() or "(문제집 미상)"
        await s.commit()
        events.publish(  # 스펙 436 — 평가 완료 알림(best-effort, 알림이지 진실 아님)
            {"type": "eval", "status": "ok", "dataset": _ds_name, "run_id": str(run_id),
             "score": report.score, "passed": report.passed, "total": report.total}
        )


async def _mark_run_error(run_id: uuid.UUID, exc: Exception) -> None:
    """실행 실패 박제 — status=error+사유(캡)+finished_at. 박제 실패는 삼킴(배경 태스크 크래시 금지)."""
    try:
        async with SessionLocal() as s:
            run = await s.get(EvalRun, run_id)
            if run is not None:
                run.status = "error"
                run.error = str(exc)[:1000]
                run.finished_at = datetime.now(UTC)
                _ds_name = (
                    await s.execute(
                        select(EvalDataset.name).where(EvalDataset.id == run.dataset_id)
                    )
                ).scalar_one_or_none() or "(문제집 미상)"
                await s.commit()
                events.publish(  # 스펙 436 — 실패 알림
                    {"type": "eval", "status": "error", "dataset": _ds_name,
                     "run_id": str(run_id), "error": str(exc)[:300]}
                )
    except Exception:
        pass


async def _execute_run(
    run_id: uuid.UUID,
    dataset_id: uuid.UUID,
    agent_pk,  # noqa: ANN001 — uuid.UUID | None이나 None은 rag 분기 전용: 주석 시 eval_run_agent(UUID) 호출이 mypy arg-type(스펙 292 P1 보고)
    principal: User | str,
    rag_collection: dict | None = None,
    overrides: dict | None = None,
    version: str | None = None,
) -> None:
    """백그라운드 실행(batch runner 미러) — 케이스 **순차**(실모델 rate-limit·격리), 상태머신
    running→ok|error. kind=rag면 rag_collection으로 검색 러너(스펙 140), 아니면 agent 러너.
    케이스/러너 실패는 하네스가 error 관측으로 접어 전체는 계속(조용한 초록 금지)."""
    try:
        cases = await _load_harness_cases(dataset_id)
        from .eval_judge import run_llm_judge

        judge_llm = await _resolve_judge_llm()

        async def run_fn(case: HarnessCase) -> dict:
            if rag_collection is not None:
                from .eval_runner import eval_run_rag

                obs = await eval_run_rag(rag_collection, case.input)
            else:
                # 위임 총량 예산 루트 주입(스펙 256, codex 후속) — 평가도 조율형 팬아웃(A→B/C/D…)이
                # 가능하므로 chat 루트와 대칭으로 카운터를 심어 breadth 폭주를 DELEGATION_MAX_TOTAL로 상한.
                # 케이스마다 새 예산(케이스 간 독립).
                obs = await eval_run_agent(
                    agent_pk,
                    case.input,
                    principal,
                    overrides,
                    version=version,
                    delegation_budget={"n": 0},
                )
            # 이 케이스의 llm_judge 기준만 순차 심판(스펙 139) — 결과를 obs에 주입, scorer는 읽기만.
            criteria = [
                arg
                for a in case.meta.get("raw_asserts", [])
                if isinstance(a, dict) and a.get("type") == "llm_judge" and (arg := a.get("arg"))
            ]
            if criteria:
                judge: dict = {}
                for crit in criteria:
                    judge[crit] = await run_llm_judge(
                        case.input, obs.get("output", ""), crit, judge_llm
                    )
                obs["judge"] = judge
            return obs

        report = await run_eval(cases, run_fn)
        await _persist_report(run_id, report)
    except Exception as exc:
        await _mark_run_error(run_id, exc)


async def _execute_group(
    specs: list[tuple],
    dataset_id: uuid.UUID,
    agent_pk: uuid.UUID,
    principal: User | str,
    version: str | None = None,
) -> None:
    """모델 비교 그룹 실행(스펙 141) — (run_id, model_name)들을 **순차**로(로컬 LLM 과점유 방지).
    개별 런 실패는 _execute_run이 error로 박제하고 다음 모델은 계속."""
    for run_id, model_name in specs:
        await _execute_run(
            run_id,
            dataset_id,
            agent_pk,
            principal,
            overrides={"model": model_name} if model_name else None,
            version=version,
        )
