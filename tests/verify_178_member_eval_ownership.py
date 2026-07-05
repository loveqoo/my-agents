"""스펙 178 검증 — 멤버 자율 평가(소유 기반) 인가 + 비용 가드.

RBAC/소유권 체크리스트(docs/spec/CLAUDE.md) — 읽기 공개(D1)·관리 소유자·실행 소유자+may_use_agent:
  T1 읽기 공개: 멤버 B가 A의 문제집·케이스 list/get 통과(can_manage=False).
  T2 관리 격리: B가 A의 dataset/case를 수정·삭제·실행·출제 → 404-fold.
  T3 자가-잠금 핀: 소유자 A는 본인 dataset 수정·케이스 추가 정상 통과.
  T4 구멍#1 봉합: A가 남의 private 에이전트를 run/suggest 대상 지정 → 404(may_use_agent).
  T5 관리자 특권: admin은 A의 dataset 관리 가능.
  T6 비용 가드: 작업량(cases×models) 상한 초과 → 422, 동시 run 상한 초과 → 429.

실행: cd packages/api && uv run python ../../tests/verify_178_member_eval_ownership.py
"""
import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import authz, eval_routes as ER  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent, EvalCase, EvalDataset, EvalRun  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Stub:
    """principal 더블 — 쿠키 유저 흉내(id + is_superuser)."""
    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.is_active = True
        self.is_verified = True
        self.email = f"u-{self.id.hex[:6]}@x"


async def _expect_status(coro, code: int, label: str) -> None:
    try:
        await coro
        check(False, f"{label} → HTTP {code}이어야 (예외 없음)")
    except HTTPException as e:
        check(e.status_code == code, f"{label} → {code} (got {e.status_code})")


async def main() -> None:
    await authz.init_authz()
    A, B, ADMIN = Stub(), Stub(), Stub(is_superuser=True)
    made_ds, made_ag, made_run = [], [], []

    def mk_agent(owner):
        a = Agent(agent_id=f"e178_{uuid.uuid4().hex[:6]}", name=f"e178-{uuid.uuid4().hex[:4]}",
                  source="ui", model="mock-chat", persona="", history_depth=5,
                  config={"model": "mock-chat", "persona": "", "memories": [], "vectorTables": [],
                          "mcps": [], "historyDepth": 5},
                  exposed={"a2a": False}, status="idle", owner_id=owner)
        return a

    try:
        # ---- 픽스처: A 소유 agent 문제집 + 케이스 1, agent_A(A소유)·agent_B(B소유 private) ----
        from api.eval_routes import DatasetIn, CaseIn, RunStartIn
        async with SessionLocal() as s:
            agent_A, agent_B = mk_agent(str(A.id)), mk_agent(str(B.id))
            s.add_all([agent_A, agent_B])
            await s.commit()
            made_ag += [agent_A.id, agent_B.id]
            aA_id, aB_id = agent_A.id, agent_B.id

        async with SessionLocal() as s:
            ds = await ER.create_dataset(DatasetIn(name=f"e178-ds-{uuid.uuid4().hex[:5]}", kind="agent"),
                                         session=s, user=A)
            ds_id = ds.id
            made_ds.append(ds_id)
        async with SessionLocal() as s:
            case = await ER.create_case(ds_id, CaseIn(name="c1", input="hi", asserts=[], order_idx=0),
                                        session=s, user=A)
            case_id = case.id

        # ---- T1 읽기 공개 ----
        async with SessionLocal() as s:
            lst = await ER.list_datasets(session=s, user=B)
            mine = [d for d in lst if d.id == ds_id]
            check(bool(mine), "T1 B가 A의 문제집 list 열람(공개)")
            check(mine and mine[0].can_manage is False, "T1 B의 can_manage=False(관리 버튼 숨김)")
            cases = await ER.list_cases(ds_id, session=s, user=B)
            check(len(cases) == 1, "T1 B가 A의 케이스 list 열람(공개)")

        # ---- T2 관리 격리(B → A 자원) ----
        async with SessionLocal() as s:
            await _expect_status(ER.update_dataset(ds_id, DatasetIn(name="x", kind="agent"), session=s, user=B), 404, "T2 B가 A dataset 수정")
        async with SessionLocal() as s:
            await _expect_status(ER.delete_dataset(ds_id, session=s, user=B), 404, "T2 B가 A dataset 삭제")
        async with SessionLocal() as s:
            await _expect_status(ER.create_case(ds_id, CaseIn(name="x", input="x", asserts=[], order_idx=1), session=s, user=B), 404, "T2 B가 A dataset에 케이스 추가")
        async with SessionLocal() as s:
            await _expect_status(ER.update_case(case_id, CaseIn(name="x", input="x", asserts=[], order_idx=0), session=s, user=B), 404, "T2 B가 A case 수정")
        async with SessionLocal() as s:
            await _expect_status(ER.delete_case(case_id, session=s, user=B), 404, "T2 B가 A case 삭제")
        async with SessionLocal() as s:
            await _expect_status(ER.start_run(ds_id, RunStartIn(agent_id=aA_id), session=s, user=B), 404, "T2 B가 A dataset 실행")
        async with SessionLocal() as s:
            await _expect_status(ER.suggest_cases(ds_id, ER.SuggestIn(agent_id=aA_id), session=s, user=B), 404, "T2 B가 A dataset 출제")

        # ---- T3 자가-잠금 핀(A는 본인 것 관리 통과) ----
        async with SessionLocal() as s:
            out = await ER.update_dataset(ds_id, DatasetIn(name=f"e178-ds2-{uuid.uuid4().hex[:5]}", kind="agent"), session=s, user=A)
            check(out.id == ds_id, "T3 소유자 A는 본인 dataset 수정 통과")
        async with SessionLocal() as s:
            c2 = await ER.create_case(ds_id, CaseIn(name="c2", input="hi2", asserts=[], order_idx=1), session=s, user=A)
            check(c2.dataset_id == ds_id, "T3 소유자 A는 본인 dataset에 케이스 추가 통과")

        # ---- T4 구멍#1: A가 남의 private 에이전트(agent_B) 대상 → 404 ----
        async with SessionLocal() as s:
            await _expect_status(ER.start_run(ds_id, RunStartIn(agent_id=aB_id), session=s, user=A), 404, "T4 A가 남의 private 에이전트로 실행")
        async with SessionLocal() as s:
            await _expect_status(ER.suggest_cases(ds_id, ER.SuggestIn(agent_id=aB_id), session=s, user=A), 404, "T4 A가 남의 private 에이전트로 출제")

        # ---- T5 관리자 특권 ----
        async with SessionLocal() as s:
            out = await ER.update_dataset(ds_id, DatasetIn(name=f"e178-admin-{uuid.uuid4().hex[:5]}", kind="agent"), session=s, user=ADMIN)
            check(out.id == ds_id, "T5 admin은 A의 dataset 관리 가능(특권)")

        # ---- T6 비용 가드 ----
        # (a) 작업량 상한: 케이스 61개(work=61>60) → A 실행 시 422.
        async with SessionLocal() as s:
            base = (await s.execute(
                __import__("sqlalchemy").select(__import__("sqlalchemy").func.count(EvalCase.id)).where(EvalCase.dataset_id == ds_id)
            )).scalar_one()
            for i in range(61 - base):
                s.add(EvalCase(dataset_id=ds_id, name=f"bulk{i}", input="x", asserts=[], order_idx=100 + i))
            await s.commit()
        async with SessionLocal() as s:
            await _expect_status(ER.start_run(ds_id, RunStartIn(agent_id=aA_id), session=s, user=A), 422, "T6 작업량(cases×models>60) 상한 → 422")
        async with SessionLocal() as s:
            # 특권은 상한 우회
            try:
                r = await ER.start_run(ds_id, RunStartIn(agent_id=aA_id), session=s, user=ADMIN)
                made_run.append(r.id)
                check(True, "T6 admin은 작업량 상한 우회(특권)")
            except HTTPException as e:
                check(False, f"T6 admin 우회 실패 (got {e.status_code})")
        # (b) 동시 run 상한: 다른 dataset에 A 소유 running run 2개 심고, 작은 dataset 실행 → 429.
        async with SessionLocal() as s:
            ds2 = EvalDataset(name=f"e178-oth-{uuid.uuid4().hex[:5]}", kind="agent", owner_id=str(A.id))
            s.add(ds2); await s.commit(); made_ds.append(ds2.id)
            for _ in range(2):
                r = EvalRun(dataset_id=ds2.id, agent_pk=aA_id, agent_name="x", status="running", total=1, owner_id=str(A.id))
                s.add(r); await s.flush(); made_run.append(r.id)
            await s.commit()
        # 작은 실행용 dataset(케이스 1) — ds_id는 이제 61케이스라 작업량 걸림 → 별도 소형 dataset.
        async with SessionLocal() as s:
            small = await ER.create_dataset(DatasetIn(name=f"e178-sm-{uuid.uuid4().hex[:5]}", kind="agent"), session=s, user=A)
            made_ds.append(small.id); small_id = small.id
        async with SessionLocal() as s:
            await ER.create_case(small_id, CaseIn(name="c", input="hi", asserts=[], order_idx=0), session=s, user=A)
        async with SessionLocal() as s:
            await _expect_status(ER.start_run(small_id, RunStartIn(agent_id=aA_id), session=s, user=A), 429, "T6 동시 run 상한(2) 초과 → 429")

        # ---- T7 배경 작업(생성/출제) 동시 상한 — codex #1·#2 ----
        # A 소유 dataset 2개를 _active_jobs에 심고 가드 직접 호출 → 429. exclude/특권/타인 소유 격리 확인.
        j1 = EvalDataset(name=f"e178-j1-{uuid.uuid4().hex[:5]}", kind="rag", owner_id=str(A.id))
        j2 = EvalDataset(name=f"e178-j2-{uuid.uuid4().hex[:5]}", kind="rag", owner_id=str(A.id))
        jB = EvalDataset(name=f"e178-jb-{uuid.uuid4().hex[:5]}", kind="rag", owner_id=str(B.id))
        async with SessionLocal() as s:
            s.add_all([j1, j2, jB]); await s.commit()
            made_ds += [j1.id, j2.id, jB.id]
        ER._active_jobs.update({j1.id, j2.id})
        try:
            async with SessionLocal() as s:
                await _expect_status(ER._member_job_guard(s, A), 429, "T7 A 배경작업 2개 in-flight → 429")
            async with SessionLocal() as s:  # 현재 락 제외하면 1개 → 통과
                try:
                    await ER._member_job_guard(s, A, exclude_id=j1.id)
                    check(True, "T7 exclude_id(현재 작업 제외)면 1개 → 통과")
                except HTTPException as e:
                    check(False, f"T7 exclude 통과 실패 (got {e.status_code})")
            async with SessionLocal() as s:  # B는 자기 in-flight 0 → 통과(소유자별 격리)
                try:
                    await ER._member_job_guard(s, B)
                    check(True, "T7 B는 A의 in-flight에 영향 없음(소유자별 격리)")
                except HTTPException as e:
                    check(False, f"T7 B 격리 실패 (got {e.status_code})")
        finally:
            ER._active_jobs.discard(j1.id); ER._active_jobs.discard(j2.id)

        # ---- T8 출제 락은 동기 획득 + 실패 시 해제(누수 없음) — codex #2 ----
        # A가 본인 dataset에 남의 private 에이전트로 출제 → 404, 그리고 _active_jobs 누수 없어야.
        async with SessionLocal() as s:
            await _expect_status(ER.suggest_cases(ds_id, ER.SuggestIn(agent_id=aB_id), session=s, user=A), 404, "T8 출제 실패(404) 경로")
        check(ds_id not in ER._active_jobs, "T8 실패해도 _active_jobs 락 누수 없음(finally 해제)")

        # ---- T9 work가 llm_judge 비용을 포함 — codex #5 ----
        # 선행: T6에서 심은 A의 running run 정리(안 하면 concurrent 429가 work 422보다 먼저 걸림).
        async with SessionLocal() as s:
            for rid in list(made_run):
                r = await s.get(EvalRun, rid)
                if r and r.status == "running":
                    r.status = "done"
            await s.commit()
        # 케이스 11개 × judge 5개 = judge 55 + cases 11 = work 66 > 60 → 422(구 공식 11×1=11이면 통과).
        async with SessionLocal() as s:
            jds = await ER.create_dataset(DatasetIn(name=f"e178-jw-{uuid.uuid4().hex[:5]}", kind="agent"), session=s, user=A)
            made_ds.append(jds.id); jds_id = jds.id
        async with SessionLocal() as s:
            for i in range(11):
                s.add(EvalCase(dataset_id=jds_id, name=f"jw{i}", input="x", order_idx=i,
                               asserts=[{"type": "llm_judge", "criterion": f"c{i}-{k}"} for k in range(5)]))
            await s.commit()
        async with SessionLocal() as s:
            await _expect_status(ER.start_run(jds_id, RunStartIn(agent_id=aA_id), session=s, user=A), 422, "T9 judge 포함 work>60 → 422")

    finally:
        # 청소
        async with SessionLocal() as s:
            for rid in made_run:
                r = await s.get(EvalRun, rid)
                if r: await s.delete(r)
            for did in made_ds:
                d = await s.get(EvalDataset, did)
                if d: await s.delete(d)  # cases/runs CASCADE
            for aid in made_ag:
                a = await s.get(Agent, aid)
                if a: await s.delete(a)
            await s.commit()

    print()
    if _fails:
        print(f"검증 실패 {len(_fails)}건:")
        for f in _fails:
            print(f"  - {f}")
        sys.exit(1)
    print("스펙 178 멤버 자율 평가 인가+비용가드 — 전부 통과.")


if __name__ == "__main__":
    asyncio.run(main())
