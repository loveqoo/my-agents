"""평가 실행 접수 게이트 — eval_runs.py에서 분할(스펙 399 P3, 순수 이동).

판정(_admission_check — 규칙 단일 출처)과 반응(수동=_assert_run_admission의 HTTP,
자동=trigger_auto_regression의 조용한 스킵)을 분리 유지(스펙 377 — 판정식 드리프트 0).
파사드는 eval_runs.py(재수출).
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .eval_guards import _active_jobs
from .eval_schemas import RunStartIn
from .models import Agent, EvalCase, EvalDataset, EvalRun, User
from .ownership import may_manage, may_use_agent


async def _resolve_run_target(
    session: AsyncSession, ds: EvalDataset, body: RunStartIn, user: User | str
) -> tuple[Agent | None, dict | None, str | None]:
    """kind별 실행 대상 해석(스펙 140) — (agent, rag_collection, target_name).
    교차 대상은 400(codex 140 #1 — 조용한 무시는 "다른 대상을 시험했다"는 오해를 만든다)."""
    if body.agent_id is not None and body.collection_id is not None:
        raise HTTPException(
            status_code=400, detail="agent_id와 collection_id는 동시에 줄 수 없습니다"
        )
    if ds.kind == "rag":
        # 스펙 193: 문제집에 고정된 컬렉션 우선. body 값은 하위호환·구버전 첫 실행(lazy 고정)용.
        coll_id = ds.collection_id or body.collection_id
        if coll_id is None:
            raise HTTPException(status_code=400, detail="RAG 문제집은 collection_id가 필요합니다")
        from .rag import resolve_search_collection

        rag_collection = await resolve_search_collection(session, coll_id)  # 404/400 자체 처리
        if (
            ds.collection_id is None
        ):  # 구버전 문제집: 첫 실행 때 고른 컬렉션을 고정(이후 재선택 불필요)
            ds.collection_id = coll_id
        return None, rag_collection, f"RAG · {rag_collection['name']}"
    if body.agent_id is None:
        raise HTTPException(status_code=400, detail="에이전트 문제집은 agent_id가 필요합니다")
    agent = await session.get(Agent, body.agent_id)
    # 스펙 178 구멍#1 봉합: 쓸 수 있는 에이전트만 평가 대상(남의 private을 UUID로 지정해도 404-fold).
    if agent is None or not may_use_agent(agent, user):
        raise HTTPException(status_code=404, detail="agent not found")
    return agent, None, agent.name


async def _admission_check(session: AsyncSession, dataset_id: uuid.UUID) -> tuple[int, str | None]:
    """실행 승인 공통 판정(스펙 377·캠페인 374 T1-3) — 빈 문제집·중복 실행 게이트 단일 출처.

    반환=(케이스 수, 거부 사유|None). 사유는 수동(`_assert_run_admission`)이 HTTP 400/409로,
    자동(`trigger_auto_regression`)이 조용한 스킵으로 **각자 반응**한다 — 판정 규칙은 여기 하나
    (드리프트 0). 경로 고유 게이트는 제외: `_active_jobs` 락은 수동만, 버전 dedupe는 자동만."""
    n_cases = (
        await session.execute(
            select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset_id)
        )
    ).scalar_one()
    if n_cases == 0:
        return n_cases, "empty"
    # 중복 실행 게이트(codex 137 #2) — 같은 문제집에 running이 있으면 거부(더블클릭·다중 탭이
    # 실모델 호출을 N배로 만드는 사고 차단. admin 전용이어도 비용 사고는 사고).
    running = (
        await session.execute(
            select(func.count(EvalRun.id)).where(
                EvalRun.dataset_id == dataset_id, EvalRun.status == "running"
            )
        )
    ).scalar_one()
    if running:
        return n_cases, "running"
    return n_cases, None


async def _assert_run_admission(session: AsyncSession, dataset_id: uuid.UUID) -> int:
    """실행 승인 게이트 3종(작업 진행 중 409 · 빈 문제집 400 · 중복 실행 409) — 케이스 수 반환."""
    if dataset_id in _active_jobs:
        # 출제/수확 진행 중 실행 금지(codex 142/143 계보) — 판정은 _active_jobs 락 단일 출처.
        # "생성 중" description 접두 보조판정은 스펙 329에서 제거(합법 생산자 소멸 — 사용자가 설명에
        # 그 문구를 넣기만 해도 실행이 409로 막히던 오탐 표면).
        raise HTTPException(
            status_code=409, detail="문제 생성이 진행 중입니다 — 완료 후 실행하세요"
        )
    n_cases, reason = await _admission_check(session, dataset_id)
    if reason == "empty":
        raise HTTPException(status_code=400, detail="케이스가 없는 문제집은 실행할 수 없습니다")
    if reason == "running":
        raise HTTPException(
            status_code=409, detail="이 문제집은 이미 실행 중입니다 — 완료 후 다시 시도하세요"
        )
    return n_cases


async def _validate_compare_models(
    session: AsyncSession, ds: EvalDataset, body: RunStartIn
) -> list[str]:
    """모델 비교(스펙 141, kind=agent 전용) 사전 검증 — 정규화된 모델 목록 반환. 이름은 레지스트리
    chat 모델로 **사전 검증**: _load_context는 미존재 이름을 기본 모델로 만회하므로(설정 만회 함정 —
    스펙 089와 동류) 여기서 안 막으면 "다른 모델로 조용히 시험"이 된다."""
    models: list[str] = [m.strip() for m in body.models if m and m.strip()]
    if not models:
        return models
    if ds.kind != "agent":
        raise HTTPException(status_code=400, detail="모델 비교는 에이전트 문제집에서만 가능합니다")
    if len(set(models)) != len(models):
        raise HTTPException(status_code=400, detail="모델 이름이 중복되었습니다")
    from .models import ModelConfig

    rows = (
        (
            await session.execute(
                select(ModelConfig.name).where(
                    ModelConfig.kind == "chat", ModelConfig.name.in_(models)
                )
            )
        )
        .scalars()
        .all()
    )
    missing = sorted(set(models) - set(rows))
    if missing:
        raise HTTPException(
            status_code=400, detail=f"레지스트리에 없는 chat 모델: {', '.join(missing)}"
        )
    return models


async def _resolve_pinned_version(
    session: AsyncSession, agent: Agent | None, body: RunStartIn, user: User | str
) -> dict | None:
    """버전 지정 평가(스펙 242) — 지정 시 그 버전 존재 검증 후 config 반환(초안=배포 전 게이트).
    미지정=None(활성 버전 config 사용)."""
    if body.agent_version is None:
        return None
    if agent is None:
        raise HTTPException(
            status_code=400, detail="agent_version은 에이전트 문제집에서만 사용합니다"
        )
    if not may_manage(agent, user):
        # 초안=미공개 작업본(codex 242 #2) — 버전 지정 평가는 그 에이전트 관리 권한 필요.
        raise HTTPException(
            status_code=403, detail="버전 지정 평가는 이 에이전트를 관리할 수 있어야 합니다"
        )
    from .models import AgentVersion

    vrow = (
        await session.execute(
            select(AgentVersion).where(
                AgentVersion.agent_pk == agent.id, AgentVersion.version == body.agent_version
            )
        )
    ).scalar_one_or_none()
    if vrow is None:
        raise HTTPException(
            status_code=404, detail=f"버전을 찾을 수 없습니다: {body.agent_version}"
        )
    return dict(vrow.config or {})
