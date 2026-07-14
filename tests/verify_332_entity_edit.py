"""verify_332 — 엔티티 문서 편집(스펙 332, 331 확장 — JSONL 행 단위 부분 재임베딩).

  E1 GET: 엔티티 문서 editable=true + JSONL 원문 왕복.
  E2 행 단위 부분 재임베딩(핵심): 행1 유지·행2 data 변경·행3 meta만 변경 →
     임베딩 호출=행2뿐(캡처 실증)·통계 reembedded 1/reused 2·행3 meta는 DB에 갱신(벡터 재사용).
  E3 스키마 위반 행 → 400 + 행 번호(업로드 입구와 동일 fail-closed 계약).
  E4 blob 없는 엔티티(스펙 312 이전 적재 꼴) → editable=false(원본 미보존 사유).
  E5 검색 meta 동반: 수정 행 동일질의 → hit.meta가 수정된 metadata.
  E6 집계==실측 청크 수.
실행: uv run python tests/_throwaway_db.py tests/verify_332_entity_edit.py
전제: dev 서버(127.0.0.1:8000) 기동 — mock 임베딩(/_remote/v1) HTTP 대상.
"""

import asyncio
import io
import json
import os
import sys
import uuid as _uuid

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

from fastapi import HTTPException, UploadFile  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

from api import rag as RAG  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import RAG_EMBED_DIMS, Chunk, Collection, Document, DocumentBlob, ModelConfig  # noqa: E402
from api.schemas import CollectionSearchIn, DocumentEditIn  # noqa: E402

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
    email = "verify332@example.com"


def _row(i: int, data: str) -> str:
    return json.dumps({"metadata": {"id": i}, "data": data}, ensure_ascii=False)


SCHEMA = {
    "type": "object",
    "required": ["metadata", "data"],
    "properties": {"metadata": {"type": "object", "required": ["id"]}},
}
R1 = "인셉션 — 꿈속에서 생각을 심는 특수 요원의 이야기, 2010년 SF 스릴러."
R2 = "올드보이 — 15년 감금의 이유를 쫓는 복수극, 2003년 미스터리."
R3 = "괴물 — 한강에 나타난 괴생명체와 한 가족의 사투, 2006년."
R2_NEW = "올드보이 — 이유 모를 15년 감금 뒤 오대수의 처절한 복수와 반전, 2003년 느와르 미스터리."
ORIG = "\n".join([_row(1, R1), _row(2, R2), _row(3, R3)])
# 행1 유지 · 행2 data 변경 · 행3 meta만 변경(id 3→30, data 동일)
EDITED = "\n".join(
    [_row(1, R1), _row(2, R2_NEW), json.dumps({"metadata": {"id": 30}, "data": R3}, ensure_ascii=False)]
)




async def _wait_ingest_ready(doc_id) -> int:
    """배경 인제스트(스펙 334) 완료 대기 → chunk_count. 실패/타임아웃은 -1."""
    import asyncio as _a
    for _ in range(100):
        async with SessionLocal() as _s:
            row = (
                await _s.execute(
                    select(Document.status, Document.chunk_count).where(Document.id == doc_id)
                )
            ).first()
        if row and row[0] == "ready":
            return row[1]
        if row and row[0] == "error":
            return -1
        await _a.sleep(0.3)
    return -1


async def _expect_http(coro, status: int, label: str) -> str:
    try:
        await coro
        check(False, f"{label} (예외 없음)")
        return ""
    except HTTPException as exc:
        check(exc.status_code == status, f"{label} (got {exc.status_code})")
        return str(exc.detail)


async def main():
    sup = _Super()
    tag = f"v332-{_uuid.uuid4().hex[:6]}"
    async with SessionLocal() as s:
        emb = (
            (await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding")))
            .scalars()
            .first()
        )
        assert emb is not None
        col = Collection(
            name=tag,
            kind="entity",
            entity_schema=SCHEMA,
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            status="empty",
            owner_id=str(sup.id),
        )
        s.add(col)
        await s.commit()
        cid = col.id

        up = UploadFile(
            io.BytesIO(ORIG.encode()),
            filename="movies.jsonl",
            headers=Headers({"content-type": "application/jsonl"}),
        )
        doc_out = await RAG.ingest_document(cid, up, s, sup)
        doc_id = doc_out.id  # expire_all 전에 박제(만료 후 속성 접근=동기 lazy-load 크래시)
        n_rows = await _wait_ingest_ready(doc_id)  # 스펙 334: 인제스트=배경 — ready 대기
        s.expire_all()  # 배경 잡이 다른 세션서 갱신한 상태 반영(identity map stale 회피)
        check(n_rows == 3, f"준비: 인제스트 3행 (got {n_rows})")

        # ── E1 GET — editable=true + JSONL 왕복 ──
        content = await RAG.get_document_content(cid, doc_id, s, sup)
        check(content.editable is True and content.text == ORIG, "E1 엔티티 editable=true+원문 왕복")

        # ── E2 행 단위 부분 재임베딩 ──
        sent: list[list[str]] = []
        orig_embed = RAG.rag_ingest.embed_texts

        async def _capture(base_url, key, model_id, chunks):
            sent.append(list(chunks))
            return await orig_embed(base_url, key, model_id, chunks)

        RAG.rag_ingest.embed_texts = _capture
        try:
            r = await RAG.update_document_content(cid, doc_id, DocumentEditIn(text=EDITED), s, sup)
        finally:
            RAG.rag_ingest.embed_texts = orig_embed
        check(
            r.chunks == 3 and r.reembedded == 1 and r.reused == 2,
            f"E2a 통계: 변경 1행만 재임베딩 (chunks={r.chunks} reembedded={r.reembedded} reused={r.reused})",
        )
        check(
            len(sent) == 1 and sent[0] == [R2_NEW],
            f"E2b 임베딩 호출=변경 행뿐 (got {[len(b) for b in sent]})",
        )
        rows = (
            await s.execute(
                select(Chunk.text, Chunk.meta).where(Chunk.document_id == doc_id).order_by(Chunk.ordinal)
            )
        ).all()
        check(
            rows[2][0] == R3 and rows[2][1] == {"id": 30},
            f"E2c meta만 변경한 행: 벡터 재사용+meta 갱신 (got {rows[2][1]})",
        )
        check(rows[1][0] == R2_NEW and rows[1][1] == {"id": 2}, "E2d 변경 행 텍스트·meta 반영")

        # ── E3 스키마 위반 행 → 400 + 행 번호 ──
        bad = "\n".join([_row(1, R1), json.dumps({"metadata": {}, "data": "id 없는 행"})])
        detail = await _expect_http(
            RAG.update_document_content(cid, doc_id, DocumentEditIn(text=bad), s, sup),
            400,
            "E3 스키마 위반 → 400",
        )
        check("2번째 줄" in detail, f"E3b 위반 행 번호 동반 (detail={detail[:80]})")

        # ── E3c NaN/Infinity 행 → 400+줄 번호(codex 332 P2 — JSONB insert 500이 아니라 파싱서 거절) ──
        nan_body = _row(1, R1) + '\n{"metadata": {"id": NaN}, "data": "비표준 상수 행"}'
        detail_nan = await _expect_http(
            RAG.update_document_content(cid, doc_id, DocumentEditIn(text=nan_body), s, sup),
            400,
            "E3c NaN 행 → 400",
        )
        check("2번째 줄" in detail_nan and "비표준" in detail_nan, f"E3d NaN 거절 사유+줄 번호 (detail={detail_nan[:80]})")

        # ── E3e 미지 kind 컬렉션 → 편집 fail-closed(codex 332 P3 — DB String(20) 화이트리스트) ──
        wcol = Collection(
            name=f"{tag}-w", kind="weird", embedding_model_id=emb.id, dims=RAG_EMBED_DIMS,
            status="empty", owner_id=str(sup.id),
        )
        s.add(wcol)
        await s.flush()
        wdoc = Document(collection_id=wcol.id, filename="w.txt", byte_size=1, status="ready")
        s.add(wdoc)
        await s.flush()
        s.add(DocumentBlob(document_id=wdoc.id, data=b"x"))
        await s.commit()
        cw = await RAG.get_document_content(wcol.id, wdoc.id, s, sup)
        check(cw.editable is False and cw.reason is not None and "알 수 없는" in cw.reason, "E3e 미지 kind editable=false")

        # ── E4 blob 없는 엔티티(312 이전 꼴) → editable=false ──
        old_doc = Document(collection_id=cid, filename="legacy.jsonl", byte_size=2, status="ready")
        s.add(old_doc)
        await s.commit()
        c4 = await RAG.get_document_content(cid, old_doc.id, s, sup)
        check(
            c4.editable is False and c4.reason is not None and "원본" in c4.reason,
            "E4 blob 없는 엔티티 editable=false(원본 미보존)",
        )

        # ── E5 검색 meta 동반(동일질의 결정화 — mock 순위는 무작위) ──
        sr = await RAG.search_collection(cid, CollectionSearchIn(query=R2_NEW, top_k=3), s, sup)
        top = sr.results[0] if sr.results else None
        check(
            top is not None and top.text == R2_NEW and top.meta == {"id": 2},
            f"E5 수정 행 최상위+meta 동반 (got meta={top.meta if top else '없음'})",
        )

        # ── E6 집계==실측 ──
        actual = (
            await s.execute(select(func.count(Chunk.id)).where(Chunk.collection_id == cid))
        ).scalar_one()
        col_cnt = (
            await s.execute(select(Collection.chunk_count).where(Collection.id == cid))
        ).scalar_one()
        check(col_cnt == actual == 3, f"E6 집계==실측 (집계 {col_cnt}·실측 {actual})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY332_OK — {passed}건 전부 통과")


asyncio.run(main())
