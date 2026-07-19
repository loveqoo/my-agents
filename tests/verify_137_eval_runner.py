"""verify_137(단계 ②) — 평가 러너: 오염 제로 + 관측 union + 실행 파이프라인 (스펙 137).

  C1 _canonical_tokens 단위: 그래프 노드 ∪ 브로커(canonical 병기) ∪ 직접형 calls_sink ∪ memory:used.
  C2 실 e2e: 자기완결 픽스처(문서 컬렉션+ui 에이전트, 스펙 400 재활 — 구 옵시디언 시드 전제 제거)에
     실제 질문(search_documents 언급 → mock 결정적 도구 호출) → trace_nodes에 rag: 토큰, error 없음.
  C3 **오염 제로 측정**: C2 실행 전후 sessions 행 수·mem0_memories 행 수 불변(자가선언 아님 — 카운트).
  C4 실행 파이프라인: 문제집+케이스(필수 rag 채점) 생성 → _execute_run → status=ok·score=1.0·
     케이스 결과 영속. 데이터셋 삭제로 run/results CASCADE 정리.

실행: uv run --project packages/api python tests/verify_137_eval_runner.py
전제 없음(자기완결) — virgin 서버(mock-llm/mock-embed 시드)에서 결정적으로 돈다.
"""

import asyncio
import io
import os
import subprocess
import sys
import uuid as _uuid

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

from sqlalchemy import func, select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import eval_routes as ER  # noqa: E402
from api.eval_runner import _canonical_tokens, eval_run_agent  # noqa: E402
from fastapi import UploadFile  # noqa: E402

from api.models import Agent, Document, EvalCaseResult, EvalRun, Session as SessionModel  # noqa: E402

_fails: list[str] = []
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
    email = "verify137r@example.com"


def _mem0_count() -> int:
    r = subprocess.run(
        [
            "docker",
            "exec",
            "my-agents-postgres-1",
            "psql",
            "-U",
            "agent",
            "-d",
            os.environ.get("DATABASE_URL", "//agents").rsplit("/", 1)[-1],  # 스펙 400: virgin DB 대응
            "-t",
            "-A",
            "-c",
            "SELECT count(*) FROM mem0_memories;",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    out = r.stdout.strip().splitlines()
    # virgin DB엔 mem0 테이블이 아직 없을 수 있다(첫 사용 시 생성) — 부재=0(오염 판정엔 동치).
    return int(out[-1]) if out else 0


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


async def _wait_ingest_ready(doc_id) -> tuple[str, int]:
    """배경 인제스트(스펙 334) 완료 대기 → (status, chunk_count)."""
    for _ in range(334):  # ~100s — 배터리 부하(다수 uvicorn 부팅) 시 30s로는 임베딩 인제스트가 늦는다
        async with async_session() as _s:
            row = (
                await _s.execute(
                    select(Document.status, Document.chunk_count).where(Document.id == doc_id)
                )
            ).first()
        if row and row[0] in ("ready", "error"):
            return row[0], row[1]
        await asyncio.sleep(0.3)
    return "(타임아웃)", -1


def part_c1():
    toks = _canonical_tokens(
        ["analyze", "delegate"],
        [{"server": "local-tools", "tool": "echo"}, {"server": "rag", "tool": "search_documents"}],
        [{"node": "broker_invoke:rag:Obsidian"}],
        used_memory=True,
    )
    check(
        "broker_invoke:rag:Obsidian" in toks and "rag:Obsidian" in toks,
        "C1a 브로커 노드 원형+canonical 병기",
    )
    check(
        "mcp:local-tools/echo" in toks and "rag:search_documents" in toks,
        "C1b 직접형 calls_sink 정규화(mcp:/rag:)",
    )
    check("memory:used" in toks and "analyze" in toks, "C1c memory:used + 그래프 노드 유지")


async def main():
    part_c1()

    # 자기완결 픽스처(스펙 400 재활) — 구 옵시디언 시드 대신 컬렉션+문서+에이전트를 직접 만든다.
    ftag = f"v137r-{_uuid.uuid4().hex[:6]}"
    admin = _Super()
    from api import rag as RG
    from api.schemas import CollectionIn

    from api.models import ModelConfig

    async with async_session() as s:
        emb = (
            await s.execute(
                select(ModelConfig).where(
                    ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True)
                )
            )
        ).scalars().first()
        col = await RG.create_collection(
            CollectionIn(name=f"{ftag}-kb", kind="document", embedding_model_id=emb.id),
            session=s,
            principal=admin,
        )
    async with async_session() as s:
        doc = await RG.ingest_document(
            col.id,
            file=_upload("note.txt", "문해력 지표는 반응 패턴과 함께 본다. A/B 테스트 핵심 노트.".encode()),
            session=s,
            principal=admin,
        )
    await _wait_ingest_ready(doc.id)
    async with async_session() as s:
        row = Agent(
            agent_id=f"agt_{ftag}",
            name=f"{ftag}-agent",
            source="ui",
            prompt="문서를 검색해 답한다.",
            config={"vectorTables": [f"{ftag}-kb"]},
            active_version="v1",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        agent_pk = row.id
        sess_before = (await s.execute(select(func.count(SessionModel.id)))).scalar_one()
    mem_before = _mem0_count()

    # mock-llm 결정적 도구 트리거(스펙 236): 질문이 도구 base명(search_documents)을 언급하면 호출.
    QUESTION = "search_documents 로 문해력 관련 내용을 찾아줘"
    obs = await eval_run_agent(agent_pk, QUESTION, _Super())
    check(not obs["error"], f"C2a error 없음 (detail={obs.get('detail')!r})")
    check(
        any(t.startswith("rag:") for t in obs["trace_nodes"]),
        f"C2b rag: 토큰 존재 (got {[t for t in obs['trace_nodes'] if 'rag' in t]})",
    )
    # 스펙 400 재활: mock-llm은 도구 결과를 본문에 반영하지 않는다(내용 반영 품질은 suite 실모델 몫)
    # — 그물 계약은 "출력 비어있지 않음"까지.
    check(bool(obs["output"].strip()), f"C2c 출력 비어있지 않음 (앞부분 {obs['output'][:60]!r})")

    async with async_session() as s:
        sess_after = (await s.execute(select(func.count(SessionModel.id)))).scalar_one()
    mem_after = _mem0_count()
    check(sess_before == sess_after, f"C3a 세션 오염 0 ({sess_before}→{sess_after})")
    check(mem_before == mem_after, f"C3b mem0 오염 0 ({mem_before}→{mem_after})")

    # C4 — 실행 파이프라인
    sup = _Super()
    tag = f"v137r-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        ds = await ER.create_dataset(ER.DatasetIn(name=f"{tag}-러너 시험"), session=s, user=sup)
    try:
        async with async_session() as s:
            await ER.create_case(
                ds.id,
                ER.CaseIn(
                    name="rag 필수 회귀",
                    input=QUESTION,
                    asserts=[
                        {"type": "trace_has", "arg": "rag:"},
                        {"type": "no_error"},
                        {"type": "output_nonempty"},
                    ],
                ),
                session=s,
                user=sup,
            )
        async with async_session() as s:
            run_row = EvalRun(
                dataset_id=ds.id,
                agent_pk=agent_pk,
                agent_name=f"{ftag}-agent",
                status="running",
                total=1,
            )
            s.add(run_row)
            await s.commit()
            run_id = run_row.id
        await ER._execute_run(run_id, ds.id, agent_pk, sup)
        async with async_session() as s:
            run = await s.get(EvalRun, run_id)
            check(
                run.status == "ok" and run.score == 1.0 and run.passed == 1,
                f"C4a run ok·score 1.0 (got {run.status}, {run.score}, {run.passed}/{run.total})",
            )
            results = (
                (await s.execute(select(EvalCaseResult).where(EvalCaseResult.run_id == run_id)))
                .scalars()
                .all()
            )
            check(
                len(results) == 1
                and results[0].case_passed
                and any(d[0].startswith("trace_has:rag:") and d[1] for d in results[0].details),
                f"C4b 케이스 결과 영속+assert 상세 (got {results[0].details if results else '없음'})",
            )
        # C4d(e2e가 잡은 500 회귀 핀) — 성적표 단건 조회가 lazy 관계를 안 건드리고 정상 응답.
        async with async_session() as s:
            detail = await ER.get_run(run_id, session=s, user=sup)
            check(
                detail.status == "ok"
                and len(detail.results) == 1
                and detail.dataset_name is not None,
                f"C4d get_run 상세 정상(MissingGreenlet 회귀 핀) (got {detail.status}, results {len(detail.results)}, ds {detail.dataset_name!r})",
            )
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds.id, session=s, user=sup)
            except Exception:
                pass
        async with async_session() as s:
            left = (
                (await s.execute(select(EvalRun).where(EvalRun.dataset_id == ds.id)))
                .scalars()
                .all()
            )
            check(left == [], "C4c 데이터셋 삭제 → run/results CASCADE")

    # C5(codex #1·#2 핀) — 좀비 sweep + 중복 실행 게이트
    tag2 = f"v137z-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        ds2 = await ER.create_dataset(ER.DatasetIn(name=f"{tag2}-좀비"), session=s, user=sup)
    try:
        async with async_session() as s:
            await ER.create_case(
                ds2.id,
                ER.CaseIn(name="c", input="q", asserts=[{"type": "no_error"}]),
                session=s,
                user=sup,
            )
        async with async_session() as s:
            zombie = EvalRun(dataset_id=ds2.id, status="running", total=1)
            s.add(zombie)
            await s.commit()
            zid = zombie.id
        # 중복 게이트: running 존재 → 409
        from fastapi import HTTPException as _HTTPExc

        async with async_session() as s:
            try:
                await ER.start_run(ds2.id, ER.RunStartIn(agent_id=agent_pk), session=s, user=sup)
                check(False, "C5a running 중 재실행 → 409여야 함")
            except _HTTPExc as e:
                check(e.status_code == 409, f"C5a 중복 실행 게이트 409 (got {e.status_code})")
        # 좀비 sweep: running → error 박제
        n = await ER.sweep_zombie_runs()
        async with async_session() as s:
            z = await s.get(EvalRun, zid)
            check(
                n >= 1 and z.status == "error" and z.finished_at is not None,
                f"C5b 좀비 sweep → error 박제 (swept {n}, status {z.status})",
            )
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds2.id, session=s, user=sup)
            except Exception:
                pass

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
