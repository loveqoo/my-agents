"""verify_193 — 평가 UX 개선 백엔드(스펙 193 P1·P3).

  P1 컬렉션 고정: rag 문제집 생성 시 collection_id 저장·왕복(DatasetOut), agent 문제집은 무시(None),
     update가 collection_id 보존, 구버전(collection_id=None) 첫 실행 시 lazy 고정.
  P3 generating: DatasetOut.generating = description "생성 중…" 마커(구조 신호 승격).
실행: uv run --project packages/api python tests/verify_193_eval_ux.py
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

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import eval_routes as ER  # noqa: E402
from api.models import Collection, EvalDataset  # noqa: E402

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
    email = "verify193@example.com"


async def main():
    sup = _Super()
    async with async_session() as s:
        col = (await s.execute(select(Collection).limit(1))).scalars().first()
    if col is None:
        print("  SKIP  실 컬렉션 없음 — collection_id 왕복/lazy 스킵(generating만 검증)")
    made: list[_uuid.UUID] = []

    async with async_session() as s:
        # ── P1: rag 생성 시 collection_id 저장·왕복 ──
        if col is not None:
            out = await ER.create_dataset(
                ER.DatasetIn(
                    name=f"v193-rag-{_uuid.uuid4().hex[:8]}", kind="rag", collection_id=col.id
                ),
                s,
                sup,
            )
            made.append(out.id)
            check(
                out.collection_id == col.id,
                f"P1a rag 생성 시 collection_id 저장·왕복 (got {out.collection_id})",
            )
            check(out.kind == "rag", "P1a kind=rag")
            # list 왕복
            lst = await ER.list_datasets(s, sup, q=None, kind=None, limit=20, offset=0)
            row = next((d for d in lst.items if d.id == out.id), None)  # 스펙 196: 페이징 봉투
            check(
                row is not None and row.collection_id == col.id,
                "P1b list_datasets DatasetOut.collection_id 왕복",
            )

            # agent 문제집은 collection_id 무시(None)
            aout = await ER.create_dataset(
                ER.DatasetIn(
                    name=f"v193-agent-{_uuid.uuid4().hex[:8]}", kind="agent", collection_id=col.id
                ),
                s,
                sup,
            )
            made.append(aout.id)
            check(
                aout.collection_id is None,
                f"P1c agent 문제집은 collection_id 무시(None) (got {aout.collection_id})",
            )

            # update가 collection_id 보존(이름만 바꿔도)
            uout = await ER.update_dataset(
                out.id, ER.DatasetIn(name=out.name + "-x", kind="rag"), s, sup
            )
            check(
                uout.collection_id == col.id,
                f"P1d update가 collection_id 보존 (got {uout.collection_id})",
            )

            # ── lazy: collection_id 없는 rag → 첫 실행 시 고정 ──
            lz = await ER.create_dataset(
                ER.DatasetIn(name=f"v193-lazy-{_uuid.uuid4().hex[:8]}", kind="rag"), s, sup
            )
            made.append(lz.id)
            check(lz.collection_id is None, "P1e 구버전 rag(collection_id 미지정)=None")
            # 케이스 1개(실행 게이트 통과용)
            await ER.create_case(
                lz.id,
                ER.CaseIn(name="c1", input="검색", asserts=[{"type": "rag_hits_gte", "arg": "1"}]),
                s,
                sup,
            )
            try:
                await ER.start_run(lz.id, ER.RunStartIn(collection_id=col.id), s, sup)
            except Exception as e:  # 실행 자체(검색)는 백그라운드 — 여기서 예외 시 로깅만
                print("   (start_run 예외:", e, ")")
            ds2 = (
                (await s.execute(select(EvalDataset).where(EvalDataset.id == lz.id)))
                .scalars()
                .first()
            )
            check(
                ds2 is not None and ds2.collection_id == col.id,
                f"P1f 첫 실행 시 collection_id lazy 고정 (got {ds2.collection_id if ds2 else None})",
            )

        # ── P3: generating = description "생성 중…" 마커 ──
        gout = await ER.create_dataset(
            ER.DatasetIn(
                name=f"v193-gen-{_uuid.uuid4().hex[:8]}",
                kind="rag",
                description="생성 중… (문제가 곧 채워집니다)",
                collection_id=(col.id if col else None),
            ),
            s,
            sup,
        )
        made.append(gout.id)
        # 스펙 400 재활: '생성 중' description 접두 보조판정은 스펙 329에서 제거됨(사용자 설명
        # 문구가 실행을 409로 막던 오탐 표면) — 판정은 _active_jobs 락 단일 출처. 설명 문구만으로는
        # generating=False가 현 계약이다.
        check(
            gout.generating is False,
            f"P3a description 문구만으로는 generating=False(스펙 329) (got {gout.generating})",
        )
        nout = await ER.create_dataset(
            ER.DatasetIn(
                name=f"v193-plain-{_uuid.uuid4().hex[:8]}", kind="agent", description="보통 설명"
            ),
            s,
            sup,
        )
        made.append(nout.id)
        check(
            nout.generating is False,
            f"P3b 일반 description → generating=False (got {nout.generating})",
        )

        # cleanup
        for did in made:
            try:
                await ER.delete_dataset(did, s, sup)
            except Exception:
                pass

    print(
        f"\n{'✅ ALL PASS (VERIFY193_OK)' if not _fails else f'❌ {len(_fails)} FAILED'} — {passed} passed"
    )
    sys.exit(0 if not _fails else 1)


asyncio.run(main())
