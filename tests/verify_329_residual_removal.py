"""verify_329 — 죽은 영역 감사 잔여 3건 제거 (스펙 329).

  V1 _parse_question 단위(구 verify_142 G1 이전 — eval_golden은 'AI 출제' 경로가 공유하는 산 코드).
  V2 generate-dataset 표면 부재: eval_routes 심볼 3종 소멸 + FastAPI 라우트 테이블에 경로 없음.
  V3 마이그레이션 그래프(회고 177 패턴): 단일 head=d5795d21f6a2·리비전 중복 0·고아 down 0.
  V4 DB 실측: chunks.token_count 컬럼 부재 + alembic_version == head.
  V5 인제스트 무회귀: token_count 없는 Chunk ORM insert→select 왕복(스키마·모델 정합).
  V6 파일 부재: _harness088 2종·verify_142·shot-142 소멸 + admin 소스에 generateEvalDataset 0.
  V7 마커 화석 제거: _is_generating이 142 "생성 중…" 접두를 더는 진행으로 안 봄(산 마커 2종은 유지).
실행: uv run python tests/_throwaway_db.py tests/verify_329_residual_removal.py  (virgin DB 전 체인 적용)
"""

import glob
import os
import re
import subprocess
import sys
import uuid as _uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "packages", "api", "src"))

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def part_v1():
    from api.eval_golden import _parse_question

    check(_parse_question("A/B 테스트에서 문해력이 중요한 이유는 무엇인가?") is not None, "V1a 유효 질문")
    check(_parse_question("문해력이 중요하다") is None, "V1b 물음표 없음 → None")
    check(_parse_question("왜?") is None, "V1c 5자 미만 → None")
    check(_parse_question("이 문단에서 말하는 핵심은?") is None, "V1d 문단 지칭 → None")
    check(_parse_question("") is None and _parse_question("  \n ") is None, "V1e 빈 응답 → None")
    check(_parse_question('"질문은 따옴표를 벗는가?"') == "질문은 따옴표를 벗는가?", "V1f 따옴표 스트립")
    check(
        _parse_question("A/B 테스트에서 문해력이 중요한 이유는 무엇인가")
        == "A/B 테스트에서 문해력이 중요한 이유는 무엇인가?",
        "V1g 의문형 어미 정규화",
    )
    check(_parse_question("문해력이 가장 중요한 요소이다") is None, "V1h 평서문 거부")


def part_v2():
    from api import eval_routes as ER
    from api.main import app

    for sym in ("generate_dataset", "GenerateIn", "_execute_generation"):
        check(not hasattr(ER, sym), f"V2a eval_routes.{sym} 소멸")
    paths = {getattr(r, "path", "") for r in app.routes}
    check("/eval/generate-dataset" not in paths, "V2b 라우트 테이블에 /eval/generate-dataset 없음")


def part_v3():
    revs, downs, dups = {}, {}, []
    for f in glob.glob(os.path.join(_ROOT, "packages", "api", "alembic", "versions", "*.py")):
        src = open(f).read()
        r = re.search(r'^revision(?::[^=]*)?\s*=\s*["\'](\w+)["\']', src, re.M)
        d = re.search(r'^down_revision(?::[^=]*)?\s*=\s*(?:["\'](\w+)["\']|None)', src, re.M)
        if r is None:
            dups.append(f"헤더 파싱 실패: {os.path.basename(f)}")
            continue
        if r.group(1) in revs:
            dups.append(r.group(1))
        revs[r.group(1)] = f
        downs[r.group(1)] = d.group(1) if d and d.group(1) else None
    check(not dups, f"V3a 리비전 중복/파싱실패 0 (got {dups})")
    children = set(downs.values()) - {None}
    heads = [r for r in revs if r not in children]
    check(heads == ["d5795d21f6a2"], f"V3b 단일 head=d5795d21f6a2 (got {heads})")
    orphans = [d for d in children if d not in revs]
    check(not orphans, f"V3c 고아 down_revision 없음 (got {orphans})")


async def part_v45():
    from sqlalchemy import select, text

    from api.db import SessionLocal
    from api.models import RAG_EMBED_DIMS, Chunk, Collection, Document, ModelConfig

    async with SessionLocal() as s:
        cols = (
            await s.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='rag_chunks'"
                )
            )
        ).scalars().all()
        # 빈 결과(테이블명 오타)로 자명 통과하지 않게 산 컬럼 존재를 함께 단언(codex 329 P1 —
        # 첫 판은 'chunks'를 조회해 false green이었다).
        check(
            "embedding" in cols and "token_count" not in cols,
            f"V4a rag_chunks에 token_count 부재(+테이블 실존) (cols={sorted(cols)})",
        )
        ver = (await s.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        check(ver == "d5795d21f6a2", f"V4b alembic_version == head (got {ver})")

        # V5 — 인제스트가 하는 그대로의 Chunk insert(모델에 token_count가 없어도 왕복 정상)
        emb_model = (
            await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding").limit(1))
        ).scalars().first()
        check(emb_model is not None, "V5a 시드 embedding 모델 존재")
        tag = f"v329-{_uuid.uuid4().hex[:6]}"
        col = Collection(name=tag, embedding_model_id=emb_model.id, dims=RAG_EMBED_DIMS)
        s.add(col)
        await s.flush()
        doc = Document(collection_id=col.id, filename=f"{tag}.txt", status="ready")
        s.add(doc)
        await s.flush()
        s.add(
            Chunk(
                document_id=doc.id,
                collection_id=col.id,
                ordinal=0,
                text="검증 청크",
                embedding=[0.0] * RAG_EMBED_DIMS,
            )
        )
        await s.commit()
        got = (
            await s.execute(select(Chunk.text).where(Chunk.collection_id == col.id))
        ).scalar_one()
        check(got == "검증 청크", "V5b Chunk insert→select 왕복")
        check(not hasattr(Chunk, "token_count"), "V5c Chunk 모델에 token_count 속성 없음")


def part_v6():
    gone = [
        "admin/src/playground/_harness088.tsx",
        "admin/_harness_088.html",
        "tests/verify_142_golden_gen.py",
        "tests/browser/shot-eval-golden-142.mjs",
    ]
    for p in gone:
        check(not os.path.exists(os.path.join(_ROOT, p)), f"V6a 소멸: {p}")
    hits = subprocess.run(
        ["grep", "-rn", "generateEvalDataset", os.path.join(_ROOT, "admin", "src")],
        capture_output=True,
        text=True,
    ).stdout.strip()
    check(hits == "", f"V6b admin 소스 generateEvalDataset 0건 (got {hits[:120]})")


def part_v7():
    from api.eval_common import _is_generating
    from api.models import EvalDataset

    check(
        _is_generating(EvalDataset(description="생성 중… (문제가 곧 채워집니다)")) is False,
        "V7a 142 접두 마커는 더는 진행 아님",
    )
    check(
        _is_generating(EvalDataset(description="x · AI 출제 중…")) is True
        and _is_generating(EvalDataset(description="x · 피드백 수확 중…")) is True,
        "V7b 산 마커 2종(출제·수확)은 유지",
    )


async def main():
    part_v1()
    part_v2()
    part_v3()
    await part_v45()
    part_v6()
    part_v7()
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY329_OK — {passed}건 전부 통과")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
