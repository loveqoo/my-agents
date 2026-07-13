"""verify_331 — RAG 문서 런타임 수정 + 부분 재임베딩 (스펙 331).

  G1 원문 왕복: GET content가 blob 원문을 그대로 반환(editable=true).
  G4 부분 재임베딩(핵심): 마지막 문단만 수정 → **변경 청크만 임베딩 호출**(embed_texts 캡처로
     실증 — 결정적 mock이라 벡터 비교는 재사용을 증명 못 한다), 통계 reused+reembedded==chunks,
     doc.chunk_count/byte_size/blob 교체·컬렉션 chunk_count 증분 정합.
  G7 검색 반영: 수정 문구로 검색 → 새 청크가 최상위 히트(mock 임베딩 결정적).
  G2 PDF: GET editable=false+사유 · PUT 400.
  G3 엔티티 컬렉션: PUT 400.
  G5 재인덱싱 중: PUT 409.
  G6 공백 본문: PUT 400(빈 문서).
  G8 비소유(member): GET/PUT 404-fold(존재 비노출).
실행: uv run python tests/_throwaway_db.py tests/verify_331_document_edit.py
전제: dev 서버(127.0.0.1:8000) 기동 — mock 임베딩(/_remote/v1) HTTP 대상.
"""

import asyncio
import io
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
    email = "verify331@example.com"


class _Member:
    id = _uuid.uuid4()
    is_superuser = False
    email = "member331@example.com"


def _upload(name: str, data: bytes, ctype: str) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name, headers=Headers({"content-type": ctype}))


async def _expect_http(coro, status: int, label: str):
    try:
        await coro
        check(False, f"{label} (예외 없음)")
    except HTTPException as exc:
        check(exc.status_code == status, f"{label} (got {exc.status_code})")


PARA1 = "첫 문단입니다. 프로젝트의 전체 개요와 목적, 대상 사용자와 핵심 가치 제안을 상세히 설명합니다."
PARA2 = "둘째 문단입니다. 시스템 아키텍처와 주요 구성 요소, 모듈 간 의존 관계와 데이터 흐름을 다룹니다."
PARA3 = "셋째 문단입니다. 스테이징과 프로덕션 배포 절차, 사전 점검 항목과 승인 단계를 정리합니다."
PARA3_NEW = "셋째 문단은 수정되었습니다. 무지개 배포 절차와 롤백 지침, 카나리 트래픽 전환 비율을 정리합니다."
ORIG = f"{PARA1}\n\n{PARA2}\n\n{PARA3}"
EDITED = f"{PARA1}\n\n{PARA2}\n\n{PARA3_NEW}"


async def main():
    sup = _Super()
    tag = f"v331-{_uuid.uuid4().hex[:6]}"
    async with SessionLocal() as s:
        emb = (
            (await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding")))
            .scalars()
            .first()
        )
        assert emb is not None, "시드 embedding 모델 필요"
        col = Collection(
            name=tag,
            kind="document",
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            chunk_size=80,
            chunk_overlap=0,
            status="empty",
            owner_id=str(sup.id),
        )
        s.add(col)
        await s.commit()
        cid = col.id

        doc_out = await RAG.ingest_document(cid, _upload("guide.md", ORIG.encode(), "text/markdown"), s, sup)
        check(doc_out.status == "ready" and doc_out.chunk_count >= 3, f"준비: 인제스트 {doc_out.chunk_count}청크")
        doc_id = doc_out.id

        # ── G1 원문 왕복 ──
        content = await RAG.get_document_content(cid, doc_id, s, sup)
        check(content.editable is True and content.text == ORIG, "G1 원문 왕복(editable=true)")

        # ── G4 부분 재임베딩 — embed_texts 캡처로 "변경분만 임베딩"을 실증 ──
        col_before = (await s.execute(select(Collection.chunk_count).where(Collection.id == cid))).scalar_one()
        old_texts = set(
            (await s.execute(select(Chunk.text).where(Chunk.document_id == doc_id))).scalars().all()
        )
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
        check(r.chunks == r.reused + r.reembedded, f"G4a 통계 정합 chunks={r.chunks}=reused {r.reused}+reembedded {r.reembedded}")
        check(r.reused >= 2 and r.reembedded >= 1, f"G4b 부분성: 재사용 {r.reused}·재임베딩 {r.reembedded}")
        embedded_texts = [t for batch in sent for t in batch]
        check(
            len(sent) == 1 and all(t not in old_texts for t in embedded_texts),
            f"G4c 임베딩 호출은 변경 청크만({len(embedded_texts)}건, 기존 텍스트 0건 포함)",
        )
        new_doc = await s.get(Document, doc_id)
        blob = await s.get(DocumentBlob, doc_id)
        check(
            new_doc is not None
            and new_doc.chunk_count == r.chunks
            and new_doc.byte_size == len(EDITED.encode())
            and blob is not None
            and blob.data == EDITED.encode(),
            "G4d doc 집계·blob 원본 교체",
        )
        col_after = (await s.execute(select(Collection.chunk_count).where(Collection.id == cid))).scalar_one()
        check(
            col_after == col_before - doc_out.chunk_count + r.chunks,
            f"G4e 컬렉션 chunk_count 증분 정합 ({col_before}→{col_after})",
        )

        # ── G7 검색 반영 — mock 임베딩은 해시 기반이라 유사 문구 순위는 무작위. **동일 텍스트**
        # 질의(코사인 1.0)로 결정화: 새 청크가 1.0 최상위 + 삭제된 구 청크는 결과에 없음. ──
        sr = await RAG.search_collection(cid, CollectionSearchIn(query=PARA3_NEW, top_k=3), s, sup)
        top = sr.results[0] if sr.results else None
        check(
            top is not None and top.text == PARA3_NEW and top.score > 0.99,
            f"G7a 새 청크가 동일질의 1.0 최상위 (got score={top.score if top else '없음'})",
        )
        check(all(PARA3 != h.text for h in sr.results), "G7b 삭제된 구 청크는 검색에 없음")

        # ── G4f 중복 신규 청크(codex 331 P2): 통계는 occurrence 기준 — 같은 텍스트 2청크면
        # reembedded=2·임베딩 호출은 유일화 1건. G4g 집계=실측(codex P1 — delete rowcount 기반). ──
        dup = "중복 문단입니다. 같은 문장이 문서 안에 두 번 등장하는 경계 사례를 검증합니다."
        sent2: list[list[str]] = []

        async def _capture2(base_url, key, model_id, chunks):
            sent2.append(list(chunks))
            return await orig_embed(base_url, key, model_id, chunks)

        RAG.rag_ingest.embed_texts = _capture2
        try:
            r2 = await RAG.update_document_content(
                cid, doc_id, DocumentEditIn(text=f"{dup}\n\n{dup}"), s, sup
            )
        finally:
            RAG.rag_ingest.embed_texts = orig_embed
        check(
            r2.chunks == 2 and r2.reembedded == 2 and r2.reused == 0,
            f"G4f 중복 청크 통계 occurrence 기준 (chunks={r2.chunks} reembedded={r2.reembedded} reused={r2.reused})",
        )
        check(
            len(sent2) == 1 and sent2[0] == [dup],
            f"G4f2 임베딩 호출은 유일화 1건 (got {[len(b) for b in sent2]})",
        )
        actual_chunks = (
            await s.execute(
                select(func.count(Chunk.id)).where(Chunk.collection_id == cid)
            )
        ).scalar_one()
        col_cnt = (
            await s.execute(select(Collection.chunk_count).where(Collection.id == cid))
        ).scalar_one()
        check(col_cnt == actual_chunks == 2, f"G4g 집계==실측 청크 수 (집계 {col_cnt}·실측 {actual_chunks})")

        # ── G2 PDF — editable=false + PUT 400 ──
        pdf_doc = Document(collection_id=cid, filename=f"{tag}.pdf", content_type="application/pdf", byte_size=4, status="ready")
        s.add(pdf_doc)
        await s.flush()
        s.add(DocumentBlob(document_id=pdf_doc.id, data=b"%PDF"))
        await s.commit()
        c2 = await RAG.get_document_content(cid, pdf_doc.id, s, sup)
        check(c2.editable is False and c2.reason is not None and "PDF" in c2.reason, "G2a PDF editable=false+사유")
        await _expect_http(
            RAG.update_document_content(cid, pdf_doc.id, DocumentEditIn(text="x"), s, sup), 400, "G2b PDF PUT → 400"
        )

        # ── G3 엔티티 컬렉션 + 비JSONL 본문 → 400 (스펙 332로 엔티티 편집이 열려, 이제 이 400은
        # "엔티티 제외"가 아니라 행 파싱 fail-closed에서 나온다 — 계약은 verify_332가 상세 단언) ──
        ecol = Collection(
            name=f"{tag}-ent", kind="entity", embedding_model_id=emb.id, dims=RAG_EMBED_DIMS,
            status="empty", owner_id=str(sup.id),
        )
        s.add(ecol)
        await s.flush()
        edoc = Document(collection_id=ecol.id, filename="rows.jsonl", byte_size=2, status="ready")
        s.add(edoc)
        await s.flush()
        s.add(DocumentBlob(document_id=edoc.id, data=b"{}"))
        await s.commit()
        await _expect_http(
            RAG.update_document_content(ecol.id, edoc.id, DocumentEditIn(text="x"), s, sup), 400, "G3 엔티티 PUT → 400"
        )

        # ── G5 재인덱싱 중 → 409 ──
        col2 = await s.get(Collection, cid)
        col2.status = "reindexing"
        await s.commit()
        await _expect_http(
            RAG.update_document_content(cid, doc_id, DocumentEditIn(text="y"), s, sup), 409, "G5 재인덱싱 중 PUT → 409"
        )
        col2 = await s.get(Collection, cid)
        col2.status = "ready"
        await s.commit()

        # ── G6 공백 본문 → 400(빈 문서) ──
        await _expect_http(
            RAG.update_document_content(cid, doc_id, DocumentEditIn(text="   \n  "), s, sup), 400, "G6 공백 본문 → 400"
        )

        # ── G8 비소유(member) → 404-fold ──
        mem = _Member()
        await _expect_http(RAG.get_document_content(cid, doc_id, s, mem), 404, "G8a 비소유 GET → 404")
        await _expect_http(
            RAG.update_document_content(cid, doc_id, DocumentEditIn(text="z"), s, mem), 404, "G8b 비소유 PUT → 404"
        )

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY331_OK — {passed}건 전부 통과")


asyncio.run(main())
