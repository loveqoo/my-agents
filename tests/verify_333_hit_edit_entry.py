"""verify_333 — 검색 히트→즉시 편집 진입 (스펙 333).

  H1 문서형: 검색 히트에 document_id 동반 + 실제 인제스트 문서와 일치.
  H2 히트의 document_id로 GET content → editable=true·원문(히트→편집 API 사슬 관통).
  H3 엔티티: 히트 document_id·meta 동반 + 같은 사슬 관통.
  H4 무회귀: 인-챗 도구 경로(SearchHit 스키마 additive) — hit dict에 기존 키 전부 보존.
실행: uv run python tests/_throwaway_db.py tests/verify_333_hit_edit_entry.py
전제: dev 서버(127.0.0.1:8000) 기동 — mock 임베딩 HTTP 대상.
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

from fastapi import UploadFile  # noqa: E402
from sqlalchemy import select  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

from api import rag as RAG  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import RAG_EMBED_DIMS, Collection, ModelConfig  # noqa: E402
from api.schemas import CollectionSearchIn  # noqa: E402

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
    email = "verify333@example.com"


DOC_TEXT = "히트 편집 진입 검증용 문단입니다. 검색과 편집을 잇는 사슬을 확인합니다."
ROW_TEXT = "라라랜드 — 재즈 피아니스트와 배우 지망생의 꿈과 사랑, 2016년 뮤지컬."


async def main():
    sup = _Super()
    tag = f"v333-{_uuid.uuid4().hex[:6]}"
    async with SessionLocal() as s:
        emb = (
            (await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding")))
            .scalars()
            .first()
        )
        assert emb is not None

        # 문서형
        col = Collection(
            name=tag, kind="document", embedding_model_id=emb.id, dims=RAG_EMBED_DIMS,
            chunk_size=200, chunk_overlap=0, status="empty", owner_id=str(sup.id),
        )
        s.add(col)
        await s.commit()
        up = UploadFile(io.BytesIO(DOC_TEXT.encode()), filename="doc.md",
                        headers=Headers({"content-type": "text/markdown"}))
        doc = await RAG.ingest_document(col.id, up, s, sup)
        sr = await RAG.search_collection(col.id, CollectionSearchIn(query=DOC_TEXT, top_k=1), s, sup)
        hit = sr.results[0]
        check(hit.document_id == doc.id, f"H1 문서형 히트 document_id 일치 (got {hit.document_id})")
        content = await RAG.get_document_content(col.id, hit.document_id, s, sup)
        check(content.editable is True and content.text == DOC_TEXT, "H2 히트→content 사슬 관통")

        # 엔티티
        ecol = Collection(
            name=f"{tag}-ent", kind="entity", embedding_model_id=emb.id, dims=RAG_EMBED_DIMS,
            status="empty", owner_id=str(sup.id),
        )
        s.add(ecol)
        await s.commit()
        row = json.dumps({"metadata": {"id": 7}, "data": ROW_TEXT}, ensure_ascii=False)
        up2 = UploadFile(io.BytesIO(row.encode()), filename="rows.jsonl",
                         headers=Headers({"content-type": "application/jsonl"}))
        edoc = await RAG.ingest_document(ecol.id, up2, s, sup)
        sr2 = await RAG.search_collection(ecol.id, CollectionSearchIn(query=ROW_TEXT, top_k=1), s, sup)
        hit2 = sr2.results[0]
        check(
            hit2.document_id == edoc.id and hit2.meta == {"id": 7},
            f"H3a 엔티티 히트 document_id+meta 동반 (got {hit2.document_id}, {hit2.meta})",
        )
        c2 = await RAG.get_document_content(ecol.id, hit2.document_id, s, sup)
        check(c2.editable is True and c2.text == row, "H3b 엔티티 히트→content 사슬 관통")

        # H4 — 코어 dict 키 additive 무회귀(인-챗 도구·trace가 쓰는 기존 키 보존)
        from api import runtime as RT

        raw = await RT.search_collections(
            [await RAG.resolve_search_collection(s, col.id)], DOC_TEXT, 1
        )
        keys = set(raw[0].keys())
        check(
            {"score", "filename", "text", "meta", "collection", "document_id"} <= keys,
            f"H4 코어 hit 키 additive (got {sorted(keys)})",
        )

        # H5 — 비노출 핀(codex 333 P3): document_id는 시험 엔드포인트(SearchHit)에는 있고,
        # 인-챗 trace/브로커 표면(_hits_detail 화이트리스트)에는 **없어야** 한다(내부 id 비유출).
        detail = RT._hits_detail(raw)
        check(
            detail and all("document_id" not in d and "text" not in d for d in detail),
            f"H5 _hits_detail에 document_id/본문 비노출 (keys={sorted(detail[0].keys()) if detail else '없음'})",
        )

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY333_OK — {passed}건 전부 통과")


asyncio.run(main())
