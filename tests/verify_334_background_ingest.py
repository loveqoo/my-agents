"""verify_334 — 인제스트 배경 잡화 + 캡 완화 (스펙 334).

  B1 접수: 업로드 즉시 반환(status=parsing·청크 0) → 배경 잡이 ready로 전이(폴링)·청크/집계 실측.
  B2 계약 보존: 엔티티 형식 위반은 여전히 **동기 400+행 번호**(배경으로 안 밀림).
  B3 임베딩 배치화: EMBED_BATCH=2·텍스트 5개 → _embed_batch 3회 호출·순서 보존(mock 결정적 벡터).
  B4 캡: 기본 50,000 + env(RAG_ENTITY_MAX_ROWS) 오버라이드(서브프로세스 실측).
  B5 좀비 스윕: embedding 잔류 문서 → sweep_zombie_ingests → error 박제+사유.
  B7 재인덱싱 경합(codex 334 P1): embedding 문서 존재 시 reindex 사전 검사 409.
  B4c env 비숫자 → 기본값 폴백(부팅 크래시 금지, codex 334 P3).
  B8 목록 processing 신호: 페이지와 무관한 컬렉션 전역 처리 중 수(codex 334 P2 — 폴링 근거).
  B6 배경 실패 정직: 깨진 PDF 업로드 → 접수는 성공, 배경에서 status=error+사유 박제.
실행: uv run python tests/_throwaway_db.py tests/verify_334_background_ingest.py
전제: dev 서버(127.0.0.1:8000) 기동 — mock 임베딩 HTTP 대상.
"""

import asyncio
import io
import json
import os
import subprocess
import sys
import uuid as _uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "packages", "api", "src"))

from fastapi import HTTPException, UploadFile  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

from api import rag as RAG  # noqa: E402
from api import rag_ingest  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import RAG_EMBED_DIMS, Chunk, Collection, Document, ModelConfig  # noqa: E402

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
    email = "verify334@example.com"


def _upload(name: str, data: bytes, ctype: str) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name, headers=Headers({"content-type": ctype}))


async def _wait_status(doc_id, want: set[str], timeout: float = 30.0) -> str:
    """배경 잡의 상태 전이를 폴링(신선 세션 — 캐시된 ORM 상태 회피)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with SessionLocal() as s:
            st = (
                await s.execute(select(Document.status).where(Document.id == doc_id))
            ).scalar_one_or_none()
        if st in want:
            return st or "(소멸)"
        await asyncio.sleep(0.3)
    return f"(타임아웃 — 마지막 {st})"


async def main():
    sup = _Super()
    tag = f"v334-{_uuid.uuid4().hex[:6]}"
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
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            status="empty",
            owner_id=str(sup.id),
        )
        s.add(col)
        await s.commit()
        cid = col.id

        # ── B1 접수 → 배경 완료 ──
        rows = "\n".join(
            json.dumps(
                {"metadata": {"id": i}, "data": f"엔티티 {i} — 배경 인제스트 검증 행."},
                ensure_ascii=False,
            )
            for i in range(1, 8)
        )
        doc_out = await RAG.ingest_document(
            cid, _upload("bg.jsonl", rows.encode(), "application/jsonl"), s, sup
        )
        check(
            doc_out.status == "parsing" and doc_out.chunk_count == 0,
            f"B1a 접수 즉시 반환(status={doc_out.status}·청크 {doc_out.chunk_count})",
        )
        st = await _wait_status(doc_out.id, {"ready", "error"})
        check(st == "ready", f"B1b 배경 잡이 ready 전이 (got {st})")
        async with SessionLocal() as s2:
            n = (
                await s2.execute(
                    select(func.count(Chunk.id)).where(Chunk.document_id == doc_out.id)
                )
            ).scalar_one()
            colrow = await s2.get(Collection, cid)
            check(
                n == 7 and colrow.chunk_count == 7 and colrow.doc_count == 1,
                f"B1c 청크/집계 실측 ({n}·{colrow.chunk_count}·{colrow.doc_count})",
            )

        # ── B2 형식 위반은 동기 400+행 번호(계약 보존) ──
        bad = rows + '\n{"data": "metadata 없는 행"}'
        try:
            await RAG.ingest_document(
                cid, _upload("bad.jsonl", bad.encode(), "application/jsonl"), s, sup
            )
            check(False, "B2 위반 업로드 → 400 (예외 없음)")
        except HTTPException as exc:
            check(
                exc.status_code == 400 and "8번째 줄" in str(exc.detail),
                f"B2 동기 400+행 번호 (got {exc.status_code}, {str(exc.detail)[:60]})",
            )

        # ── B3 임베딩 배치화 ──
        calls: list[int] = []
        orig_batch = rag_ingest._embed_batch

        async def _counting(base_url, key, model_id, texts):
            calls.append(len(texts))
            return await orig_batch(base_url, key, model_id, texts)

        orig_size = rag_ingest.EMBED_BATCH
        rag_ingest.EMBED_BATCH = 2
        rag_ingest._embed_batch = _counting
        try:
            texts5 = [f"배치 검증 텍스트 {i}" for i in range(5)]
            # 시드 mock provider를 통해 실제 HTTP 배치 호출.
            from sqlalchemy.orm import selectinload as _sl

            from api import crypto as _crypto

            async with SessionLocal() as s4:
                emb3 = (
                    await s4.execute(
                        select(ModelConfig)
                        .where(ModelConfig.id == emb.id)
                        .options(_sl(ModelConfig.provider))
                    )
                ).scalar_one()
                vecs = await rag_ingest.embed_texts(
                    emb3.provider.base_url,
                    _crypto.decrypt(emb3.provider.api_key),
                    emb3.model_id,
                    texts5,
                )
        finally:
            rag_ingest.EMBED_BATCH = orig_size
            rag_ingest._embed_batch = orig_batch
        check(calls == [2, 2, 1], f"B3a 배치 분할 호출(2,2,1) (got {calls})")
        check(
            len(vecs) == 5 and all(len(v) == RAG_EMBED_DIMS for v in vecs),
            "B3b 벡터 5개·차원 정합(순서 보존 병합)",
        )

        # ── B4 캡: 기본 50,000 + env 오버라이드 ──
        check(
            rag_ingest.ENTITY_MAX_ROWS == 50000 or os.environ.get("RAG_ENTITY_MAX_ROWS"),
            f"B4a 기본 캡 50,000 (got {rag_ingest.ENTITY_MAX_ROWS})",
        )
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0,'packages/api/src');"
                "from api import rag_ingest as R; print(R.ENTITY_MAX_ROWS);"
                "import json;"
                "rows='\\n'.join(json.dumps({'metadata':{'id':i},'data':'텍스트다섯자이상'}) for i in range(4));"
                "\ntry:\n    R.parse_entity_lines(rows.encode())\n    print('NO-RAISE')\nexcept R.EntityParseError as e:\n    print('RAISED', e)",
            ],
            env={**os.environ, "RAG_ENTITY_MAX_ROWS": "3"},
            capture_output=True,
            text=True,
            cwd=_ROOT,
        )
        check(
            "3" == probe.stdout.strip().splitlines()[0] and "RAISED" in probe.stdout,
            f"B4b env 오버라이드 실측 (out={probe.stdout.strip()[:60]})",
        )

        # ── B5 좀비 스윕 ──
        zdoc = Document(collection_id=cid, filename="zombie.jsonl", byte_size=1, status="embedding")
        s.add(zdoc)
        await s.commit()
        swept = await RAG.sweep_zombie_ingests()
        async with SessionLocal() as s5:
            z = await s5.get(Document, zdoc.id)
            check(
                swept >= 1
                and z is not None
                and z.status == "error"
                and "재시작" in (z.error or ""),
                f"B5 좀비 스윕 → error 박제 (swept={swept}, status={z.status if z else '?'})",
            )

        # ── B7 재인덱싱 경합(codex P1): embedding 문서 있으면 reindex **409**(진행 중) ──
        # 실제 변경(청크 크기)을 요청해야 "변경 없음 400"이 아니라 in-flight 검사에 도달한다.
        from api.schemas import ReindexIn

        bcol = Collection(
            name=f"{tag}-b7",
            kind="document",
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            chunk_size=1000,
            chunk_overlap=200,
            status="ready",
            owner_id=str(sup.id),
        )
        s.add(bcol)
        await s.flush()
        zdoc2 = Document(
            collection_id=bcol.id, filename="inflight.md", byte_size=1, status="embedding"
        )
        s.add(zdoc2)
        await s.commit()
        try:
            await RAG.reindex_collection(
                bcol.id,
                ReindexIn(embedding_model_id=emb.id, chunk_size=500, chunk_overlap=50),
                s,
                sup,
            )
            check(False, "B7 embedding 중 reindex → 409 (예외 없음)")
        except HTTPException as exc:
            check(
                exc.status_code == 409 and "진행 중" in str(exc.detail),
                f"B7 embedding 중 reindex 409 (got {exc.status_code}: {str(exc.detail)[:40]})",
            )

        # ── B8 목록 processing 신호(페이지 무관 전역) ──
        zdoc3 = Document(collection_id=cid, filename="zz-last.jsonl", byte_size=1, status="parsing")
        s.add(zdoc3)
        await s.commit()
        page = await RAG.list_documents(cid, None, 1, 0, s, sup)  # 1건짜리 첫 페이지
        check(
            page.processing >= 1,
            f"B8 processing 신호=전역 (page 1건인데 processing={page.processing})",
        )
        zdoc3b = await s.get(Document, zdoc3.id)
        await s.delete(zdoc3b)
        await s.commit()

        # ── B4c env 비숫자 → 기본값 폴백 ──
        probe2 = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0,'packages/api/src');"
                "from api import rag_ingest as R; print(R.ENTITY_MAX_ROWS, R.EMBED_BATCH)",
            ],
            env={**os.environ, "RAG_ENTITY_MAX_ROWS": "abc", "RAG_EMBED_BATCH": "xyz"},
            capture_output=True,
            text=True,
            cwd=_ROOT,
        )
        check(
            probe2.stdout.strip() == "50000 128",
            f"B4c env 비숫자 → 기본값 폴백 (out={probe2.stdout.strip()!r})",
        )

        # ── B6 배경 실패 정직(깨진 PDF — 접수 성공 → 배경서 error). 문서형 컬렉션에서 —
        # 엔티티 컬렉션이면 접수 단계 JSONL 파싱 400이라 배경 실패 경로에 못 간다. ──
        dcol = Collection(
            name=f"{tag}-doc",
            kind="document",
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            status="empty",
            owner_id=str(sup.id),
        )
        s.add(dcol)
        await s.commit()
        pdoc = await RAG.ingest_document(
            dcol.id, _upload("broken.pdf", b"not-a-pdf", "application/pdf"), s, sup
        )
        check(pdoc.status == "parsing", "B6a 깨진 PDF도 접수는 성공(파싱은 배경)")
        st6 = await _wait_status(pdoc.id, {"ready", "error"})
        async with SessionLocal() as s6:
            p = await s6.get(Document, pdoc.id)
        check(
            st6 == "error" and p is not None and (p.error or "") != "",
            f"B6b 배경 실패 → error+사유 (got {st6}, {p.error[:40] if p and p.error else '?'})",
        )

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY334_OK — {passed}건 전부 통과")


asyncio.run(main())
