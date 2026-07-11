"""문제 저작 라우트(스펙 291 분할) — 골든 생성(142) + AI 출제(143·195) + 피드백 수확(209 P2).

세 경로 모두 배경 LLM 작업: 상태는 dataset.description에 박제(진행 마커 → 완료/실패 tail 치환),
락은 eval_guards._active_jobs(엔드포인트가 동기 획득, 배경 finally가 해제). description-tail
로직이 세 경로에 복제 결합이라 한 모듈에 둔다(스펙 291 지도 G8).
"""

import uuid

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_principal
from .background import spawn
from .db import SessionLocal, get_or_404, get_session
from .eval_common import _dataset_or_404, _dataset_out, router
from .eval_guards import _active_jobs, _helper_llm, _member_job_guard
from .eval_schemas import (
    DatasetOut,
    GenerateIn,
    HarvestCountOut,
    HarvestIn,
    HelperStatusOut,
    SuggestIn,
)
from .models import Agent, EvalCase, EvalDataset, MessageFeedback, Session, User
from .ownership import assert_may_manage, is_privileged, may_use_agent, owner_of

# ----------------------------- 골든셋 자동 생성 (스펙 142) -----------------------------


async def _execute_generation(dataset_id: uuid.UUID, collection_id: uuid.UUID, count: int) -> None:
    """백그라운드 골든 생성 — 완료/실패를 dataset.description에 박제(조용한 빈 문제집 금지).
    케이스 기준은 자기일관 골든 3종: 출처 문서 회수 + 결과 존재 + 오류 없음."""
    from .eval_golden import generate_golden_cases

    _active_jobs.add(dataset_id)
    try:
        from .mem_config import _default_chat_model, llm_cfg_of, model_usable

        async with SessionLocal() as s:
            cm = await _default_chat_model(s)
        if not model_usable(cm):
            raise RuntimeError("기본 chat 모델 미설정 — 질문 생성 불가")
        assert cm is not None  # model_usable 보장(TypeGuard는 negative 분기 narrow 안 함)
        llm_cfg = llm_cfg_of(cm)
        result = await generate_golden_cases(collection_id, count, llm_cfg)
        async with SessionLocal() as s:
            ds = await s.get(EvalDataset, dataset_id)
            if ds is None:
                return
            for i, c in enumerate(result["cases"]):
                s.add(
                    EvalCase(
                        dataset_id=dataset_id,
                        name=f"골든 {i + 1} · {c['filename'][:60]}",
                        input=c["question"],
                        order_idx=i,
                        asserts=[
                            {"type": "rag_source_contains", "arg": c["filename"][:500]},
                            {"type": "rag_hits_gte", "arg": "1"},
                            {"type": "no_error"},
                        ],
                    )
                )
            made = len(result["cases"])
            if made == 0:
                # 조용한 빈 문제집 금지(codex 142) — 0건은 성공이 아니라 실패다.
                ds.description = (
                    f"생성 실패: 케이스 0건 (요청 {count}, 건너뜀 {result['skipped']}) — "
                    "컬렉션 문서가 너무 짧거나 생성 모델 응답이 형식을 벗어났습니다. 삭제 후 다시 시도하세요"
                )
            else:
                ds.description = (
                    f"자동 생성 {made}건 (요청 {count}"
                    + (f", 건너뜀 {result['skipped']}" if result["skipped"] else "")
                    + ") — 문제는 열어서 검토·수정하세요"
                )
            await s.commit()
    except Exception as exc:
        try:
            async with SessionLocal() as s:
                ds = await s.get(EvalDataset, dataset_id)
                if ds is not None:
                    ds.description = f"생성 실패: {str(exc)[:200]} — 삭제 후 다시 시도하세요"
                    await s.commit()
        except Exception:
            pass
    finally:
        _active_jobs.discard(dataset_id)


@router.post("/generate-dataset", response_model=DatasetOut, status_code=202)
async def generate_dataset(
    body: GenerateIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> DatasetOut:
    """컬렉션에서 RAG 문제집 자동 생성(스펙 142) — 문제집 즉시 반환, 케이스는 백그라운드 생성
    (완료/실패는 description으로 확인). 컬렉션 완전성은 검색 해석기로 사전 검증."""
    from .rag import resolve_search_collection

    await resolve_search_collection(session, body.collection_id)  # 404/400 사전 검증
    # 스펙 178 비용 가드 — 비특권 유저의 배경 생성 flood 차단(codex #1). 특권 무제한.
    if not is_privileged(user):
        await _member_job_guard(session, user)  # 생성 전 기존 in-flight만 카운트
    ds = EvalDataset(
        name=body.name,
        description="생성 중… (문제가 곧 채워집니다)",
        kind="rag",
        owner_id=owner_of(user),
        collection_id=body.collection_id,
    )  # 스펙 193: 생성 컬렉션을 문제집에 고정
    session.add(ds)
    try:
        await session.commit()
    except Exception as err:
        await session.rollback()
        raise HTTPException(status_code=409, detail="같은 이름의 문제집이 이미 있습니다") from err
    _active_jobs.add(ds.id)  # 동기 등록 — create_task 전 창을 닫아 flood 카운트 누락 방지(codex #1)
    spawn(_execute_generation(ds.id, body.collection_id, body.count))
    return _dataset_out(ds, 0, user)


# ----------------------------- AI 출제 (스펙 143 — 평가 도우미 1탄) -----------------------------


@router.get("/helper-status", response_model=HelperStatusOut)
async def helper_status(
    session: AsyncSession = Depends(get_session),
    _user: User | str = Depends(current_principal),
) -> HelperStatusOut:
    """도우미 가용성 — UI가 버튼 활성/비활성+사유 툴팁에 사용(정직 비활성)."""
    _llm, reason = await _helper_llm(session)
    return HelperStatusOut(available=_llm is not None, reason=reason)


async def _execute_suggestion(
    dataset_id: uuid.UUID, agent_pk: uuid.UUID, count: int, llm_cfg: dict, prior_desc: str | None
) -> None:
    """백그라운드 출제 — 기존 문제 보존(추가만), description에 상태 박제(142 패턴).
    order_idx는 기존 최대값 뒤로 이어붙인다. 게이트는 _active_jobs(메모리 락)."""
    from .eval_suggest import suggest_agent_cases

    # 락(_active_jobs)은 엔드포인트가 동기 획득(codex #2). 여기선 완료 시 finally에서 해제만.
    try:
        result = await suggest_agent_cases(agent_pk, count, llm_cfg)
        async with SessionLocal() as s:
            ds = await s.get(EvalDataset, dataset_id)
            if ds is None:
                return
            base_idx = (
                await s.execute(
                    select(func.coalesce(func.max(EvalCase.order_idx), -1)).where(
                        EvalCase.dataset_id == dataset_id
                    )
                )
            ).scalar_one() + 1
            for i, c in enumerate(result["cases"]):
                s.add(
                    EvalCase(
                        dataset_id=dataset_id,
                        name=f"AI 출제 {base_idx + i + 1} ({'RAG' if c['label'] == 'rag' else '역할'})",
                        input=c["question"],
                        order_idx=base_idx + i,
                        asserts=c["asserts"],
                    )
                )
            made = len(result["cases"])
            tail = (
                f"AI 출제 {made}건 추가 (요청 {count}"
                + (f", 건너뜀 {result['skipped']}" if result["skipped"] else "")
                + ")"
                if made
                else f"AI 출제 실패: 0건 (요청 {count}, 건너뜀 {result['skipped']})"
            )
            # 완료 표기는 **현재** description 기준(codex 143 — 진행 중 사용자 편집 보존):
            # "AI 출제 중…" 접미가 남아 있으면 치환, 사용자가 바꿨으면 그 값 뒤에 덧붙인다.
            cur = ds.description or ""
            if cur.endswith("AI 출제 중…"):
                ds.description = cur[: -len("AI 출제 중…")].rstrip(" ·") or None
                ds.description = f"{ds.description} · {tail}" if ds.description else tail
            else:
                ds.description = f"{cur} · {tail}" if cur else tail
            await s.commit()
    except Exception as exc:
        try:
            async with SessionLocal() as s:
                ds = await s.get(EvalDataset, dataset_id)
                if ds is not None:
                    ds.description = (
                        f"{prior_desc + ' · ' if prior_desc else ''}AI 출제 실패: {str(exc)[:150]}"
                    )
                    await s.commit()
        except Exception:
            pass
    finally:
        _active_jobs.discard(dataset_id)


async def _execute_generation_append(
    dataset_id: uuid.UUID,
    collection_id: uuid.UUID,
    count: int,
    llm_cfg: dict,
    prior_desc: str | None,
) -> None:
    """RAG 문제집 AI 출제(스펙 195) — 골든 생성을 **기존 문제집에 추가**(order_idx 이어붙임).
    generate_dataset(신규 문제집)과 달리 append + suggest 패턴 description(기존 보존). name은 해시
    (스펙 195 — 유저 비노출, 성적표엔 input이 뜬다). 락 해제는 finally."""
    import secrets

    from .eval_golden import generate_golden_cases

    try:
        result = await generate_golden_cases(collection_id, count, llm_cfg)
        async with SessionLocal() as s:
            ds = await s.get(EvalDataset, dataset_id)
            if ds is None:
                return
            base_idx = (
                await s.execute(
                    select(func.coalesce(func.max(EvalCase.order_idx), -1)).where(
                        EvalCase.dataset_id == dataset_id
                    )
                )
            ).scalar_one() + 1
            for i, c in enumerate(result["cases"]):
                s.add(
                    EvalCase(
                        dataset_id=dataset_id,
                        name=f"case-{secrets.token_hex(4)}",
                        input=c["question"],
                        order_idx=base_idx + i,
                        asserts=[
                            {"type": "rag_source_contains", "arg": c["filename"][:500]},
                            {"type": "rag_hits_gte", "arg": "1"},
                            {"type": "no_error"},
                        ],
                    )
                )
            made = len(result["cases"])
            tail = (
                f"AI 출제 {made}건 추가 (요청 {count}"
                + (f", 건너뜀 {result['skipped']}" if result["skipped"] else "")
                + ")"
                if made
                else f"AI 출제 실패: 0건 (요청 {count}, 건너뜀 {result['skipped']})"
            )
            cur = ds.description or ""
            if cur.endswith("AI 출제 중…"):
                ds.description = cur[: -len("AI 출제 중…")].rstrip(" ·") or None
                ds.description = f"{ds.description} · {tail}" if ds.description else tail
            else:
                ds.description = f"{cur} · {tail}" if cur else tail
            await s.commit()
    except Exception as exc:
        try:
            async with SessionLocal() as s:
                ds = await s.get(EvalDataset, dataset_id)
                if ds is not None:
                    ds.description = (
                        f"{prior_desc + ' · ' if prior_desc else ''}AI 출제 실패: {str(exc)[:150]}"
                    )
                    await s.commit()
        except Exception:
            pass
    finally:
        _active_jobs.discard(dataset_id)


@router.post("/datasets/{dataset_id}/suggest-cases", response_model=DatasetOut, status_code=202)
async def suggest_cases(
    dataset_id: uuid.UUID,
    body: SuggestIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> DatasetOut:
    """문제집 AI 출제 — 기존 문제 보존+추가, 백그라운드(상태=description). agent=에이전트 구성 기반(143),
    rag=고정 컬렉션 골든 생성 append(195). 둘 다 소유자만·비용가드·도우미 실모델 필요."""
    ds = await _dataset_or_404(session, dataset_id)
    assert_may_manage(
        ds, user, not_found_detail="dataset not found"
    )  # 소유자만 출제(비소유 404-fold)
    if ds.kind == "rag" and ds.collection_id is None:  # 스펙 195: rag는 고정 컬렉션 필요
        raise HTTPException(
            status_code=400,
            detail="이 RAG 문제집에 고정된 컬렉션이 없습니다 — 먼저 시험 실행으로 컬렉션을 고정하세요",
        )
    if dataset_id in _active_jobs:
        raise HTTPException(status_code=409, detail="이미 출제가 진행 중입니다")
    _active_jobs.add(
        dataset_id
    )  # 동기 락 — 배경 태스크로 미루면 중복 출제 TOCTOU(codex #2). check와 사이에 await 없음.
    try:
        agent_pk = None
        if (
            ds.kind == "agent"
        ):  # 스펙 178 구멍#1: 쓸 수 있는 에이전트만 출제 대상(남의 private 미노출).
            agent = await session.get(Agent, body.agent_id) if body.agent_id else None
            if agent is None or not may_use_agent(agent, user):
                raise HTTPException(status_code=404, detail="agent not found")
            agent_pk = agent.id
        # 스펙 178 비용 가드 — 비특권 배경 작업 동시 상한(codex #1·#2). 현재 락은 제외 카운트.
        if not is_privileged(user):
            await _member_job_guard(session, user, exclude_id=dataset_id)
        llm_cfg, reason = await _helper_llm(session)
        if llm_cfg is None:
            raise HTTPException(status_code=400, detail=f"도우미 사용 불가: {reason}")
        prior = ds.description
        ds.description = f"{prior + ' · ' if prior else ''}AI 출제 중…"
        await session.commit()
        if ds.kind == "rag":  # 스펙 195: 고정 컬렉션 골든을 기존 문제집에 append
            spawn(
                _execute_generation_append(dataset_id, ds.collection_id, body.count, llm_cfg, prior)
            )
        else:
            assert (
                agent_pk is not None
            )  # kind는 agent|rag 둘뿐 — rag는 위 분기, agent는 위에서 설정(404 가드)
            spawn(_execute_suggestion(dataset_id, agent_pk, body.count, llm_cfg, prior))
    except Exception:
        _active_jobs.discard(dataset_id)  # create_task까지 못 가면 배경 finally가 안 돌아 락이 샌다
        raise
    n = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id))
    ).scalar_one()
    return _dataset_out(ds, n, user)


# ----------------------------- 피드백 수확 (스펙 209 Phase 2) -----------------------------


async def _unharvested_count(session: AsyncSession, agent_pk: uuid.UUID) -> int:
    """이 에이전트 세션들의 미수확 피드백 수(harvested_case_pk IS NULL)."""
    return (
        await session.execute(
            select(func.count(MessageFeedback.id))
            .select_from(MessageFeedback)
            .join(Session, Session.id == MessageFeedback.session_pk)
            .where(Session.agent_pk == agent_pk, MessageFeedback.harvested_case_pk.is_(None))
        )
    ).scalar_one()


@router.get("/harvest-count", response_model=HarvestCountOut)
async def harvest_count(
    agent_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> HarvestCountOut:
    """수확 가능 피드백 수 + 기존 수확 문제집. 에이전트 소유자/admin만(수확=관리 행위, 비소유 404-fold)."""
    # 미존재 → 404(특권도, codex P2 F4 — assert_may_manage(None,superuser)는 통과해버림)
    agent = await get_or_404(session, Agent, agent_id, detail="agent not found")
    assert_may_manage(
        agent, user, not_found_detail="agent not found"
    )  # 소유자/admin만(존재 비노출)
    ds = (
        await session.execute(
            select(EvalDataset.id).where(EvalDataset.source_agent_pk == agent_id).limit(1)
        )
    ).scalar_one_or_none()
    return HarvestCountOut(available=await _unharvested_count(session, agent_id), dataset_id=ds)


@router.post("/datasets/harvest", response_model=DatasetOut, status_code=202)
async def harvest_feedback(
    body: HarvestIn,
    session: AsyncSession = Depends(get_session),
    user: User | str = Depends(current_principal),
) -> DatasetOut:
    """에이전트 피드백(👍/👎) → 초안 평가 케이스 수확. 에이전트별 "피드백 수확" 문제집(source_agent_pk로
    idempotent 재사용)에 draft로 append, 배경 LLM 작업(기준 합성). 소유권=에이전트 소유자/admin(비소유
    404-fold). 초안 게이트: 자동 활성화 없음 — 관리자가 EvalView에서 검토(스펙 209 §C)."""
    # 미존재 → 404(특권도, codex P2 F4)
    agent = await get_or_404(session, Agent, body.agent_id, detail="agent not found")
    assert_may_manage(
        agent, user, not_found_detail="agent not found"
    )  # 소유자/admin만(존재 비노출)
    agent_name, agent_owner = agent.name, agent.owner_id  # 롤백 후 만료 대비 캡처

    # 동일 에이전트 동시 수확 직렬화(codex P2 F2) — advisory xact 락. 이게 없으면 두 첫-수확이 둘 다
    # "문제집 없음"을 보고 각자 생성(하나는 이름충돌→해시명) → 2문제집·같은 피드백 이중수확.
    # 락은 이 트랜잭션 종료 시 해제되고, 그 무렵엔 문제집이 존재해 뒤 요청은 _active_jobs로 409.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"harvest:{body.agent_id}"}
    )

    # 에이전트별 수확 문제집 find-or-create(source_agent_pk로 idempotent — 재수확은 같은 문제집에 append).
    ds = (
        await session.execute(
            select(EvalDataset).where(EvalDataset.source_agent_pk == body.agent_id).limit(1)
        )
    ).scalar_one_or_none()
    if ds is None:
        import secrets

        # 소유는 **에이전트 소유자**(수확자 아님, codex P2 F5) — admin이 남의 에이전트를 수확해도 그
        # 에이전트 소유자가 문제집을 관리·검토하게. shared(owner None)면 특권만 관리(fail-closed).
        ds = EvalDataset(
            name=f"피드백 수확 · {agent_name}"[:120],
            description="응답 피드백(👍/👎) 수확 문제집 — 관리자 검토 후 활성화",
            kind="agent",
            source_agent_pk=body.agent_id,
            owner_id=agent_owner,
        )
        session.add(ds)
        try:
            await session.flush()
        except Exception:
            # 이름 유니크 충돌(동명 다른 에이전트) — 해시명 재시도. (source_agent_pk 경합은 advisory
            # 락이 이미 막으므로 여기 도달=이름 충돌.)
            await session.rollback()
            ds = EvalDataset(
                name=f"피드백 수확 · {secrets.token_hex(4)}",
                description="응답 피드백(👍/👎) 수확 문제집 — 관리자 검토 후 활성화",
                kind="agent",
                source_agent_pk=body.agent_id,
                owner_id=agent_owner,
            )
            session.add(ds)
            await session.flush()

    if ds.id in _active_jobs:
        raise HTTPException(status_code=409, detail="이미 수확이 진행 중입니다")
    _active_jobs.add(
        ds.id
    )  # 동기 락(중복 수확 TOCTOU 차단, suggest 패턴) — check와 사이 await 없음
    try:
        if not is_privileged(user):
            await _member_job_guard(
                session, user, exclude_id=ds.id
            )  # 비특권 배경 작업 동시 상한(스펙 178)
        # 도우미 LLM은 **선택** — 있으면 기준을 다듬고, mock/미설정이면 폴백 템플릿으로 저하(수확은 질문이
        # 실제 사용자 메시지라 LLM 없이도 유효, suggest와 다름). 그래서 None이어도 400 안 함.
        llm_cfg, _reason = await _helper_llm(session)
        prior = ds.description
        ds.description = f"{prior + ' · ' if prior else ''}피드백 수확 중…"
        await session.commit()
        spawn(_execute_harvest(ds.id, body.agent_id, llm_cfg, prior))
    except Exception:
        _active_jobs.discard(ds.id)  # create_task까지 못 가면 배경 finally 미실행 → 락 누수
        raise
    n = (
        await session.execute(select(func.count(EvalCase.id)).where(EvalCase.dataset_id == ds.id))
    ).scalar_one()
    return _dataset_out(ds, n, user)


async def _execute_harvest(
    dataset_id: uuid.UUID, agent_pk: uuid.UUID, llm_cfg: dict | None, prior_desc: str | None
) -> None:
    """배경 수확 — 미수확 피드백→케이스(기준 LLM 합성), 케이스별 harvested_case_pk 스탬프(재수확 방지).
    기존 케이스 보존(append). description에 상태 박제(suggest 패턴). 게이트=_active_jobs(엔드포인트 획득)."""
    from .eval_harvest import harvest_agent_feedback

    mark = "피드백 수확 중…"
    try:
        async with SessionLocal() as s:
            result = await harvest_agent_feedback(s, agent_pk, llm_cfg)
            ds = await s.get(EvalDataset, dataset_id)
            if ds is None:
                return
            base_idx = (
                await s.execute(
                    select(func.coalesce(func.max(EvalCase.order_idx), -1)).where(
                        EvalCase.dataset_id == dataset_id
                    )
                )
            ).scalar_one() + 1
            made = 0
            for i, c in enumerate(result["cases"]):
                liked = "좋아요" if c["label"] == "feedback:up" else "싫어요"
                case = EvalCase(
                    dataset_id=dataset_id,
                    name=f"피드백 {liked} {base_idx + i + 1}",
                    input=c["question"],
                    order_idx=base_idx + i,
                    asserts=c["asserts"],
                )
                s.add(case)
                await s.flush()  # case.id 확보
                # 이 피드백을 수확됨으로 스탬프(재수확 방지·링크). 소유는 불변(created_by 안 건드림).
                fb = await s.get(MessageFeedback, c["feedback_id"])
                if fb is not None:
                    fb.harvested_case_pk = case.id
                made += 1
            tail = (
                f"피드백 수확 {made}건 추가"
                + (f", 건너뜀 {result['skipped']}" if result["skipped"] else "")
                if made
                else f"피드백 수확: 0건 (건너뜀 {result['skipped']})"
            )
            cur = ds.description or ""
            if cur.endswith(mark):
                ds.description = cur[: -len(mark)].rstrip(" ·") or None
                ds.description = f"{ds.description} · {tail}" if ds.description else tail
            else:
                ds.description = f"{cur} · {tail}" if cur else tail
            await s.commit()
    except Exception as exc:
        try:
            async with SessionLocal() as s:
                ds = await s.get(EvalDataset, dataset_id)
                if ds is not None:
                    ds.description = f"{prior_desc + ' · ' if prior_desc else ''}피드백 수확 실패: {str(exc)[:150]}"
                    await s.commit()
        except Exception:
            pass
    finally:
        _active_jobs.discard(dataset_id)
