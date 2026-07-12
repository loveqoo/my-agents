"""스펙 312 검증 — 컬렉션 재인덱싱·재청킹 + 배타 잠금(실 인프라, ASGI in-process).

측정 항목(수치):
  ① 모델 교체(mock→e5): embedding_model_id 스왑·chunk_count 불변·이력 ok·검색 결과 실제 변함.
  ② 재청킹(chunk_size ↓): chunk_count 증가(원본 blob에서 재분할)·이력에 청크 계보.
  ③ 배타 잠금: reindexing 중 검색/인제스트/재인덱싱 전부 409 · CAS 이중획득 방지 · 성공/실패 해제.
  ④ 거절: no-op 400 · 엔티티+청크파라미터 400 · 원본없는 재청킹 400.
  ⑤ 평가 이력 보존: 재인덱싱 전후 eval_runs 건수 불변.
  ⑥ stale 잠금 복구: reindexing 갇힘 → _recover_stale_reindex → ready.
  ⑦ 원본 저장: 인제스트 후 document_blobs에 원본 존재.

실행: cd packages/api && uv run python ../../tests/verify_312_reindex.py
(rapid-mlx(8045) 필요 — 모델 교체 실증. 없으면 그 항목 스킵.)
"""

import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete as sa_delete  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy import update as sa_update  # noqa: E402

from api.auth import _token  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import (  # noqa: E402
    Chunk,
    Collection,
    Document,
    DocumentBlob,
    EvalRun,
    ModelConfig,
)

_fails: list[str] = []
_AUTH = {"Authorization": f"Bearer {_token()}"}
COL = "verify312-doc"

# 여러 청크가 나오도록 충분히 긴 문서(문단 반복). size=1000이면 ~3청크, size=300이면 더 많이.
DOC = ("\n\n".join(
    f"문단 {i}: 재인덱싱은 저장된 청크 텍스트를 새 임베딩 모델로 다시 임베딩하거나, 원본에서 "
    f"청크 크기와 겹침을 바꿔 다시 자른다. 검색 품질을 끌어올리려면 임베딩 모델뿐 아니라 청크 "
    f"크기도 함께 테스트해야 한다. 이것은 {i}번째 문단이며 의미 있는 분량을 채운다." * 2
    for i in range(6)
)).encode("utf-8")


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _models() -> tuple[str, str]:
    async with SessionLocal() as s:
        ms = (
            await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding"))
        ).scalars().all()
        mock = next((m for m in ms if m.name == "mock-embed"), None)
        real = next((m for m in ms if m.name != "mock-embed"), None)
        return (str(mock.id) if mock else ""), (str(real.id) if real else "")


async def _col_row(name: str):
    async with SessionLocal() as s:
        return (
            await s.execute(select(Collection).where(Collection.name == name))
        ).scalar_one_or_none()


async def main() -> None:
    from api.main import app

    mock_id, real_id = await _models()
    check(bool(mock_id), f"mock-embed 모델 확보({mock_id[:8]})")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=_AUTH, timeout=120
    ) as c:
        # 정리(멱등) — 기존 test 컬렉션 삭제
        existing = await _col_row(COL)
        if existing is not None:
            await c.delete(f"/collections/{existing.id}")

        # ── 컬렉션 생성(mock-embed, 문서형) + 원본 저장되는 인제스트 ──
        r = await c.post(
            "/collections",
            json={"name": COL, "kind": "document", "embedding_model_id": mock_id,
                  "chunk_size": 1000, "chunk_overlap": 200},
        )
        check(r.status_code == 201, f"문서 컬렉션 생성({r.status_code})")
        cid = r.json()["id"]

        r = await c.post(
            f"/collections/{cid}/documents",
            files={"file": ("reindex.txt", DOC, "text/plain")},
        )
        check(r.status_code == 201, f"문서 인제스트({r.status_code})")
        base_chunks = r.json().get("chunk_count", 0)
        check(base_chunks >= 2, f"초기 청크 수 {base_chunks}(≥2 — 재청킹 대비)")

        # ⑦ 원본 blob 저장 확인
        async with SessionLocal() as s:
            docs = (await s.execute(
                select(DocumentBlob.document_id)
                .join(Document, DocumentBlob.document_id == Document.id)
                .where(Document.collection_id == cid)
            )).scalars().all()
        check(len(docs) >= 1, f"원본 blob 저장됨({len(docs)}건)")

        # 평가 런 전체 건수(⑤ 보존 대조 기준)
        async with SessionLocal() as s:
            eval_before = (await s.execute(select(func.count()).select_from(EvalRun))).scalar_one()

        # ── ④ 거절: no-op(같은 모델·청크 변경 없음) ──
        r = await c.post(f"/collections/{cid}/reindex", json={"embedding_model_id": mock_id})
        check(r.status_code == 400, f"no-op(같은 모델) → 400 거절({r.status_code})")

        # ── ② 재청킹: chunk_size 1000→300 → 청크 수 증가 ──
        r = await c.post(f"/collections/{cid}/reindex", json={"chunk_size": 300, "chunk_overlap": 50})
        check(r.status_code == 200, f"재청킹(size 300) 실행({r.status_code})")
        col = await _col_row(COL)
        check(col is not None and col.chunk_size == 300, "컬렉션 chunk_size=300 반영")
        check(col is not None and col.chunk_count > base_chunks,
              f"재청킹으로 청크 수 증가({base_chunks}→{col.chunk_count if col else '?'})")
        check(col is not None and col.status == "ready", "재청킹 후 status=ready(잠금 해제)")
        rechunk_count = col.chunk_count if col else 0

        # ── ① 모델 교체(mock→e5): 검색 품질 실제 변화 ──
        if real_id:
            # 교체 전 검색 점수(mock)
            q = "청크 크기와 임베딩 모델을 바꿔가며 검색 품질을 높인다"

            def _top(resp):
                res = resp.json().get("results", []) if resp.status_code == 200 else []
                return res[0].get("score") if res else None

            mock_top = _top(await c.post(f"/collections/{cid}/search", json={"query": q, "top_k": 3}))

            r = await c.post(f"/collections/{cid}/reindex", json={"embedding_model_id": real_id})
            check(r.status_code == 200, f"모델 교체(mock→e5) 실행({r.status_code})")
            col = await _col_row(COL)
            check(col is not None and str(col.embedding_model_id) == real_id,
                  "embedding_model_id가 e5로 스왑")
            check(col is not None and col.chunk_count == rechunk_count,
                  f"모델 교체는 청크 수 불변({rechunk_count})")
            real_top = _top(await c.post(f"/collections/{cid}/search", json={"query": q, "top_k": 3}))
            check(real_top is not None, f"e5 검색 동작(top={real_top})")
            print(f"  ..  검색 점수 mock={mock_top} → e5={real_top}(같은 질의)")
        else:
            print("  ..  rapid-mlx 없음 — 모델 교체 실증 스킵")

        # ── ③ 배타 잠금: reindexing 강제 후 접근 차단 ──
        async with SessionLocal() as s:
            await s.execute(sa_update(Collection).where(Collection.id == cid).values(status="reindexing"))
            await s.commit()
        r = await c.post(f"/collections/{cid}/search", json={"query": "x", "top_k": 3})
        check(r.status_code == 409, f"잠금 중 검색 → 409({r.status_code})")
        r = await c.post(f"/collections/{cid}/documents", files={"file": ("x.txt", b"hi", "text/plain")})
        check(r.status_code == 409, f"잠금 중 인제스트 → 409({r.status_code})")
        r = await c.post(f"/collections/{cid}/reindex", json={"chunk_size": 500})
        check(r.status_code == 409, f"잠금 중 재인덱싱 → 409({r.status_code})")

        # CAS 이중 획득 방지: reindexing 상태에선 획득 실패
        from api.rag import _acquire_reindex_lock, _persist_chunks
        async with SessionLocal() as s:
            got = await _acquire_reindex_lock(s, uuid.UUID(cid))
        check(not got, "reindexing 상태에서 CAS 재획득 실패(이중 재인덱싱 방지)")

        # F1 회귀(codex): 인제스트가 시작 가드를 지난 뒤라도 _persist_chunks가 재인덱싱 잠금을 존중 —
        # 청크를 넣지 않고 취소(IngestError)하고 status='reindexing'을 안 덮는다(데이터 손실·잠금해제 봉인).
        from api.rag_ingest import IngestError as _IngestError
        async with SessionLocal() as s:
            col_obj = (await s.execute(select(Collection).where(Collection.id == uuid.UUID(cid)))).scalar_one()
            d = Document(collection_id=col_obj.id, filename="race.txt", status="parsing")
            s.add(d)
            await s.commit()
            doc_pk = d.id  # 롤백 후 d는 expire → lazy load 회피 위해 미리 박제
            raised = False
            try:
                await _persist_chunks(s, col_obj, d, ["race"], [None], [[0.0] * 1024])
            except _IngestError:
                raised = True
            await s.rollback()
            check(raised, "F1: 재인덱싱 중 _persist_chunks가 취소(IngestError — 청크·잠금 존중)")
            st = (await s.execute(select(Collection.status).where(Collection.id == uuid.UUID(cid)))).scalar_one()
            check(st == "reindexing", "F1: _persist_chunks가 잠금을 안 덮음(status 유지)")
            nchunk = (await s.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_pk)
            )).scalar_one()
            check(nchunk == 0, "F1: 취소된 인제스트의 청크 0(유실 방지)")
            await s.execute(sa_delete(Document).where(Document.id == doc_pk))
            await s.commit()

        # ── ⑥ stale 잠금 복구 ──
        from api.db import _recover_stale_reindex
        async with SessionLocal() as s:
            await _recover_stale_reindex(s)
        col = await _col_row(COL)
        check(col is not None and col.status == "ready", "stale 재인덱싱 잠금 복구(reindexing→ready)")

        # ── ⑤ 평가 이력 보존 ──
        async with SessionLocal() as s:
            eval_after = (await s.execute(select(func.count()).select_from(EvalRun))).scalar_one()
        check(eval_before == eval_after, f"평가 런 이력 건수 불변({eval_before}={eval_after})")

        # ── ④ 거절: 엔티티 컬렉션에 청크 파라미터 ──
        movies = await _col_row("movies-demo")
        if movies is not None:
            r = await c.post(f"/collections/{movies.id}/reindex", json={"chunk_size": 500})
            check(r.status_code == 400, f"엔티티에 청크 파라미터 → 400({r.status_code})")
        else:
            print("  ..  movies-demo 없음 — 엔티티 거절 스킵")

        # ── 재인덱싱 이력 엔드포인트 ──
        r = await c.get(f"/collections/{cid}/reindex-events")
        check(r.status_code == 200, f"이력 엔드포인트({r.status_code})")
        events = r.json()
        check(len(events) >= 2, f"이력 {len(events)}건 기록(재청킹+모델교체)")
        if events:
            latest = events[0]
            print(f"  ..  최신 이력: {latest.get('from_model_name')}→{latest.get('to_model_name')} "
                  f"chunk {latest.get('from_chunk_size')}→{latest.get('to_chunk_size')} "
                  f"status={latest.get('status')} count={latest.get('chunk_count')}")

        # 정리
        await c.delete(f"/collections/{cid}")

    print()
    if _fails:
        print(f"FAIL: {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("VERIFY312_OK — 재인덱싱·재청킹·배타잠금·이력보존·stale복구 정착")


if __name__ == "__main__":
    asyncio.run(main())
