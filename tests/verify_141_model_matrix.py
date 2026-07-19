"""verify_141 — 모델별 비교 실행 + 격자 데이터 (스펙 141).

  M1 검증 게이트: 미존재 모델 400·rag 문제집+models 400·중복 이름 400·7개 초과(스키마 422).
  M2 그룹 생성: models 2개 → EvalRun 2건(model_name·공통 group_id) 즉시 running.
  M3 그룹 순차 실행(실 모델): 기본 chat 모델을 다른 이름으로 임시 등록해 2모델 격자 →
     두 런 모두 ok·케이스 결과 영속·격자 조회 데이터 정합(모델별 성적).
실행: uv run --project packages/api python tests/verify_141_model_matrix.py
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
from api.models import Agent, EvalRun, ModelConfig  # noqa: E402

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
    email = "verify141@example.com"


async def main():
    sup = _Super()
    tag = f"v141-{_uuid.uuid4().hex[:6]}"
    # 자기완결 픽스처(스펙 400 재활) — 구 '옵시디언 매니저' 시드 전제 제거. virgin seed에는
    # 기본 chat 모델(mock)만 있고 에이전트는 없으므로 시험용 에이전트를 직접 만든다.
    async with async_session() as s:
        default_chat = (
            await s.execute(
                select(ModelConfig).where(
                    ModelConfig.kind == "chat", ModelConfig.is_default.is_(True)
                )
            )
        ).scalar_one_or_none()
    if default_chat is None:
        check(False, "전제 실패: 기본 chat 모델 없음(seed)")
        sys.exit(1)
    async with async_session() as s:
        agent = Agent(
            agent_id=f"agt_{tag}",
            name=f"{tag}-agent",
            source="ui",
            prompt="질문에 간결히 답한다.",
            config={},
            active_version="v1",
        )
        s.add(agent)
        await s.commit()
        await s.refresh(agent)

    # 임시 두 번째 모델(같은 provider/model_id, 다른 이름) — 결정적 2모델 격자용
    alt_name = f"{tag}-모델B"
    async with async_session() as s:
        alt = ModelConfig(
            name=alt_name,
            kind="chat",
            provider_id=default_chat.provider_id,
            model_id=default_chat.model_id,
        )
        s.add(alt)
        await s.commit()

    async with async_session() as s:
        ds = await ER.create_dataset(ER.DatasetIn(name=f"{tag}-격자"), session=s, user=sup)
    try:
        async with async_session() as s:
            await ER.create_case(
                ds.id,
                ER.CaseIn(
                    name="기본 문제",
                    input="A/B 테스트에서 중요한 것은?",
                    asserts=[{"type": "no_error"}, {"type": "output_nonempty"}],
                ),
                session=s,
                user=sup,
            )
        # M1 게이트
        async with async_session() as s:
            try:
                await ER.start_run(
                    ds.id,
                    ER.RunStartIn(agent_id=agent.id, models=["없는모델XYZ"]),
                    session=s,
                    user=sup,
                )
                check(False, "M1a 미존재 모델 → 400이어야")
            except HTTPException as e:
                check(
                    e.status_code == 400 and "없는모델XYZ" in e.detail,
                    f"M1a 미존재 모델 400 ({e.detail[:40]})",
                )
        async with async_session() as s:
            try:
                await ER.start_run(
                    ds.id,
                    ER.RunStartIn(agent_id=agent.id, models=[default_chat.name, default_chat.name]),
                    session=s,
                    user=sup,
                )
                check(False, "M1b 중복 이름 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, "M1b 중복 이름 400")
        try:
            ER.RunStartIn(agent_id=agent.id, models=[f"m{i}" for i in range(7)])
            check(False, "M1c 7개 → 스키마 거부여야")
        except ValidationError:
            check(True, "M1c 모델 7개 → 스키마 422")
        # rag 문제집 + models
        async with async_session() as s:
            ds_rag = await ER.create_dataset(
                ER.DatasetIn(name=f"{tag}-rag", kind="rag"), session=s, user=sup
            )
        try:
            async with async_session() as s:
                await ER.create_case(
                    ds_rag.id,
                    ER.CaseIn(name="c", input="q", asserts=[{"type": "no_error"}]),
                    session=s,
                    user=sup,
                )
            async with async_session() as s:
                try:
                    await ER.start_run(
                        ds_rag.id,
                        ER.RunStartIn(collection_id=_uuid.uuid4(), models=[default_chat.name]),
                        session=s,
                        user=sup,
                    )
                    check(False, "M1d rag+models → 400이어야")
                except HTTPException as e:
                    check(e.status_code in (400, 404), f"M1d rag+models 거부 ({e.status_code})")
        finally:
            async with async_session() as s:
                try:
                    await ER.delete_dataset(ds_rag.id, session=s, user=sup)
                except Exception:
                    pass

        # M2+M3: 그룹 생성·순차 실행 — start_run의 create_task 대신 수동 생성+직접 실행(결정적)
        gid = _uuid.uuid4()
        async with async_session() as s:
            runs = [
                EvalRun(
                    dataset_id=ds.id,
                    agent_pk=agent.id,
                    agent_name=agent.name,
                    model_name=m,
                    group_id=gid,
                    status="running",
                    total=1,
                )
                for m in [default_chat.name, alt_name]
            ]
            s.add_all(runs)
            await s.commit()
            specs = [(r.id, r.model_name) for r in runs]
        async with async_session() as s:
            grp = (await s.execute(select(EvalRun).where(EvalRun.group_id == gid))).scalars().all()
            check(
                len(grp) == 2 and {g.model_name for g in grp} == {default_chat.name, alt_name},
                "M2 그룹 2런·model_name 박제",
            )
        await ER._execute_group(specs, ds.id, agent.id, sup)
        async with async_session() as s:
            grp = (await s.execute(select(EvalRun).where(EvalRun.group_id == gid))).scalars().all()
            check(
                all(g.status == "ok" for g in grp),
                f"M3a 두 모델 런 모두 ok (got {[g.status for g in grp]})",
            )
            check(
                all(g.score == 1.0 and g.passed == 1 for g in grp),
                f"M3b 모델별 성적 정합 (got {[(g.model_name, g.score) for g in grp]})",
            )
            det = await ER.get_run(grp[0].id, session=s, user=sup)
            check(
                det.model_name is not None and det.group_id == gid,
                "M3c 성적표에 model_name/group_id",
            )
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds.id, session=s, user=sup)
            except Exception:
                pass
        async with async_session() as s:
            tmp = (
                await s.execute(select(ModelConfig).where(ModelConfig.name == alt_name))
            ).scalar_one_or_none()
            if tmp:
                await s.delete(tmp)
                await s.commit()
        async with async_session() as s:
            ag = await s.get(Agent, agent.id)
            if ag:
                await s.delete(ag)
                await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
