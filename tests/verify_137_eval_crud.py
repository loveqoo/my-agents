"""verify_137(단계 ①) — 평가 문제집/케이스 CRUD + 선언 asserts 검증 (스펙 137).

  A build_asserts: 유효 type 매핑·미지 type ValueError·arg 누락 ValueError(닫힌 집합 fail-closed).
  B CRUD 왕복(실 DB, 라우트 직접 호출 — verify_093 principal 스텁 패턴): 데이터셋 생성→케이스 생성
    (필수 도구 asserts 포함)→목록→수정→미지 type 400→케이스 삭제→데이터셋 삭제(CASCADE).
실행: uv run --project packages/api python tests/verify_137_eval_crud.py
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
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api.eval_harness import build_asserts  # noqa: E402
from api import eval_routes as ER  # noqa: E402
from api.models import EvalCase  # noqa: E402

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
    """principal 스텁(verify_093 패턴) — 라우트 직접 호출용."""

    id = _uuid.uuid4()
    is_superuser = True
    email = "verify137@example.com"


def part_a():
    scorers = build_asserts(
        [
            {"type": "trace_has", "arg": "rag:"},
            {"type": "trace_lacks", "arg": "mcp:danger/"},
            {"type": "no_error"},
            {"type": "output_contains", "arg": "문해력"},
        ]
    )
    check(
        len(scorers) == 4 and scorers[0][0] == "trace_has:rag:",
        f"A1 유효 매핑 4종 (got {[s[0] for s in scorers]})",
    )
    for bad, label in [
        # 스펙 400 재활: 구 픽스처의 미지 type 예가 llm_judge였는데 스펙 139서 정식 등록됨 — 진짜 미지명으로.
        ([{"type": "bogus_type_400", "arg": "x"}], "미지 type"),
        ([{"type": "trace_has"}], "arg 누락"),
        (["문자열"], "비-dict"),
        ([{"type": "trace_has", "arg": "x" * 501}], "arg 500자 초과(codex #3)"),
    ]:
        try:
            build_asserts(bad)
            check(False, f"A2 {label} → ValueError여야 함")
        except ValueError:
            check(True, f"A2 {label} → ValueError(fail-closed)")


async def part_b():
    tag = f"v137-{_uuid.uuid4().hex[:6]}"
    sup = _Super()
    async with async_session() as s:
        ds = await ER.create_dataset(
            ER.DatasetIn(name=f"{tag}-문제집", kind="agent"), session=s, user=sup
        )
        check(ds.kind == "agent" and ds.case_count == 0, "B1 데이터셋 생성")
    try:
        async with async_session() as s:
            case = await ER.create_case(
                ds.id,
                ER.CaseIn(
                    name="rag 필수",
                    input="노트에서 A/B 테스트 정리해줘",
                    asserts=[{"type": "trace_has", "arg": "rag:"}, {"type": "no_error"}],
                ),
                session=s,
                user=sup,
            )
            check(len(case.asserts) == 2, "B2 케이스 생성(필수 도구 asserts)")
        async with async_session() as s:
            try:
                await ER.create_case(
                    ds.id,
                    ER.CaseIn(name="bad", input="x", asserts=[{"type": "없는채점", "arg": "y"}]),
                    session=s,
                    user=sup,
                )
                check(False, "B3 미지 type 케이스 → 400이어야 함")
            except HTTPException as e:
                check(e.status_code == 400, f"B3 미지 type → 400 (got {e.status_code})")
        async with async_session() as s:
            rows = await ER.list_cases(ds.id, session=s, user=sup)
            check(len(rows) == 1 and rows[0].name == "rag 필수", f"B4 목록 1건 (got {len(rows)})")
        async with async_session() as s:
            upd = await ER.update_case(
                case.id,
                ER.CaseIn(name="rag 필수 v2", input="수정", asserts=[{"type": "output_nonempty"}]),
                session=s,
                user=sup,
            )
            check(
                upd.name == "rag 필수 v2" and upd.asserts == [{"type": "output_nonempty"}],
                "B5 케이스 수정",
            )
        async with async_session() as s:
            dss = await ER.list_datasets(session=s, user=sup, q=None, kind=None, limit=20, offset=0)
            mine = [d for d in dss.items if d.id == ds.id]
            check(mine and mine[0].case_count == 1, f"B6 데이터셋 목록에 case_count=1")
    finally:
        async with async_session() as s:
            try:
                await ER.delete_dataset(ds.id, session=s, user=sup)
            except Exception:
                pass
        async with async_session() as s:
            left = (
                (await s.execute(select(EvalCase).where(EvalCase.dataset_id == ds.id)))
                .scalars()
                .all()
            )
            check(left == [], "B7 데이터셋 삭제 → 케이스 CASCADE(잔존 0)")


async def main():
    part_a()
    await part_b()
    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
