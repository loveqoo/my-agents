"""스펙 435 검증 — 인제스트 재시도(보존 원본) + 진행률.

A 재시도: 실패(status=error) 문서를 **재업로드 없이** 다시 인제스트 → ready·청크 생성.
   게이트: 성공 문서 400 · 진행 중 문서 400 · 재인덱싱 중 409.
B 진행률: 인제스트 중 list_documents가 progress {done,total} 증가를 보이고, 완료 후 None.

virgin DB 전용(_throwaway_db.py).
실행: uv run python tests/_throwaway_db.py tests/verify_435_ingest_retry_progress.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "api" / "src"))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from api import rag as RAG  # noqa: E402, N812
from api.db import SessionLocal  # noqa: E402
from api.models import Chunk, Collection, Document, DocumentBlob, ModelConfig  # noqa: E402
from api.schemas import CollectionIn  # noqa: E402

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        fails.append(msg)


class _Super:
    id = uuid.uuid4()
    is_superuser = True
    is_active = True
    is_verified = True
    email = "v435@local"


async def _mkdoc(s: AsyncSession, cid: uuid.UUID, data: bytes, status: str) -> uuid.UUID:
    d = Document(
        collection_id=cid, filename="v435.txt", content_type="text/plain",
        status=status, byte_size=len(data),
    )
    s.add(d)
    await s.commit()
    s.add(DocumentBlob(document_id=d.id, data=data))
    await s.commit()
    return d.id


async def main() -> int:
    sup = _Super()
    data = ("재시도 검증 본문입니다. " * 300).encode()
    async with SessionLocal() as s:
        emb = (
            await s.execute(select(ModelConfig).where(ModelConfig.name == "mock-embed"))
        ).scalar_one()
        col = await RAG.create_collection(
            CollectionIn(name=f"v435-{uuid.uuid4().hex[:6]}", embedding_model_id=emb.id,
                         chunk_size=200, chunk_overlap=40),
            s, sup,
        )
        cid = uuid.UUID(str(col.id))

        # ── A1: 실패(error) 문서 재시도 → ready + 청크 생성 ──
        did = await _mkdoc(s, cid, data, "error")
        await s.execute(update(Document).where(Document.id == did).values(error="일시 실패(주입)"))
        await s.commit()
        out = await RAG.reingest_document(cid, did, s, sup)
        check(out.status == "parsing", f"A1 재시도 접수 → status parsing (got {out.status})")
        for _ in range(100):  # 배경 인제스트 완료 대기
            await asyncio.sleep(0.2)
            async with SessionLocal() as s2:
                st = (
                    await s2.execute(select(Document.status).where(Document.id == did))
                ).scalar_one()
            if st in ("ready", "error"):
                break
        async with SessionLocal() as s3:
            st, err = (
                await s3.execute(
                    select(Document.status, Document.error).where(Document.id == did)
                )
            ).first()
            n = (
                await s3.execute(select(func.count(Chunk.id)).where(Chunk.document_id == did))
            ).scalar_one()
        check(st == "ready", f"A1 재시도 완료 status=ready (got {st!r} err={err!r})")
        check(n > 0, f"A1 청크 생성 {n}개(원본 재업로드 없이)")
        check(err is None, "A1 이전 오류 문구 정리")

        # ── A2: 성공(ready) 문서 재시도는 400 ──
        raised = None
        try:
            await RAG.reingest_document(cid, did, s, sup)
        except HTTPException as exc:
            raised = exc.status_code
        check(raised == 400, f"A2 성공 문서 재시도 → 400 (got {raised})")

        # ── A3: 진행 중(parsing) 문서 재시도는 400 ──
        did2 = await _mkdoc(s, cid, data, "parsing")
        raised2 = None
        try:
            await RAG.reingest_document(cid, did2, s, sup)
        except HTTPException as exc:
            raised2 = exc.status_code
        check(raised2 == 400, f"A3 진행 중 문서 재시도 → 400 (got {raised2})")

        # ── A4: 재인덱싱 중 재시도는 409 ──
        await s.execute(update(Document).where(Document.id == did2).values(status="error"))
        await s.execute(update(Collection).where(Collection.id == cid).values(status="reindexing"))
        await s.commit()
        raised3 = None
        try:
            await RAG.reingest_document(cid, did2, s, sup)
        except HTTPException as exc:
            raised3 = exc.status_code
        check(raised3 == 409, f"A4 재인덱싱 중 재시도 → 409 (got {raised3})")
        await s.execute(update(Collection).where(Collection.id == cid).values(status="ready"))
        await s.commit()

    # ── B: 진행률 — 큰 문서 인제스트 중 done 증가, 완료 후 None ──
    big = ("진행률 검증 본문. " * 20000).encode()  # 다수 배치 유도
    async with SessionLocal() as s:
        did3 = await _mkdoc(s, cid, big, "error")
        await RAG.reingest_document(cid, did3, s, sup)
    seen: list[int] = []
    done_none = False
    for _ in range(200):
        await asyncio.sleep(0.1)
        async with SessionLocal() as s4:
            page = await RAG.list_documents(cid, None, 50, 0, s4, sup)
        row = next((d for d in page.items if d.id == did3), None)
        if row is None:
            continue
        if row.progress:
            seen.append(row.progress["done"])
        if row.status in ("ready", "error"):
            done_none = row.progress is None
            break
    check(len(seen) > 0, f"B1 인제스트 중 progress 노출 (샘플 {len(seen)}회: {seen[:5]}…)")
    check(len(set(seen)) > 1 or (seen and seen[0] > 0), f"B2 진행 수치 관측 (values={sorted(set(seen))[:6]})")
    check(done_none, "B3 완료 후 progress None(휘발 정리)")

    print("\n" + ("VERIFY435_OK — 재시도·진행률" if not fails else f"FAIL {len(fails)}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
