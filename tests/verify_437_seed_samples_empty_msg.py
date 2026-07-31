"""스펙 437 검증 — 시드 샘플 문서 + 빈 컬렉션 정직 메시지.

S1 virgin 시드: 데모 컬렉션 3종 모두 doc≥1·chunk≥1·status=ready·blob 보존(편집·재시도 계약).
S2 검색 실측: team-notes에서 "배포 절차" 히트(전수 조사 재현 질의가 이제 답을 찾음).
S3 빈 컬렉션 메시지: 빈 컬렉션만 배선한 RAG 도구 검색 → "문서가 없습니다" 정직 메시지.
S4 일부만 빈 경우: 채워진 컬렉션과 혼합이면 기존 무히트/히트 경로(오탐 방지).

virgin DB 전용. 실행: uv run python tests/_throwaway_db.py tests/verify_437_seed_samples_empty_msg.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "api" / "src"))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from api import rag_runtime  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Chunk, Collection, Document, DocumentBlob, ModelConfig  # noqa: E402

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        fails.append(msg)


async def _col_dict(s: AsyncSession, name: str) -> dict:
    c = (await s.execute(select(Collection).where(Collection.name == name))).scalar_one()
    m = await s.get(ModelConfig, c.embedding_model_id)
    prov_base = "http://127.0.0.1:8000/_remote/v1"  # mock provider base(시드 mock-embed)
    return {
        "id": c.id, "name": c.name, "embed_base_url": prov_base,
        "embed_api_key": None, "embed_model_id": m.model_id,
    }


async def main() -> int:
    # ── S1: 시드 결과(3컬렉션 적재·blob 보존) ──
    async with SessionLocal() as s:
        for name in ("docs-kb", "team-notes", "product-titles"):
            c = (await s.execute(select(Collection).where(Collection.name == name))).scalar_one()
            docs = (
                await s.execute(select(func.count(Document.id)).where(Document.collection_id == c.id))
            ).scalar_one()
            chunks = (
                await s.execute(select(func.count(Chunk.id)).where(Chunk.collection_id == c.id))
            ).scalar_one()
            blobs = (
                await s.execute(
                    select(func.count(DocumentBlob.document_id))
                    .select_from(DocumentBlob)
                    .join(Document, Document.id == DocumentBlob.document_id)
                    .where(Document.collection_id == c.id)
                )
            ).scalar_one()
            check(
                c.status == "ready" and docs >= 1 and chunks >= 1 and blobs >= 1
                and c.doc_count == docs and c.chunk_count == chunks,
                f"S1 {name}: status={c.status} docs={docs} chunks={chunks} blobs={blobs} 집계 일치",
            )

    # ── S2: 검색 실측(팀 노트 "배포 절차") — mock 라우트가 필요하므로 in-process ASGI 없이
    # search_collections 코어 직접 + 임베딩은 mock 라우트 대신 결정적 함수로 동일 공간 재현 ──
    # (코어는 HTTP 임베딩을 부르므로 라이브 서버 없는 virgin 환경에선 monkeypatch로 결정 임베딩 주입)
    from api import rag_ingest
    from api.mock_remote import _det_embedding
    from api.models import RAG_EMBED_DIMS

    async def _fake_embed(base_url, api_key, model_id, texts):  # noqa: ANN001, ARG001, ANN202
        return [_det_embedding(t, RAG_EMBED_DIMS) for t in texts]

    orig = rag_ingest.embed_texts
    rag_ingest.embed_texts = _fake_embed
    try:
        async with SessionLocal() as s:
            col = await _col_dict(s, "team-notes")
        hits = await rag_runtime.search_collections([col], "배포 절차", top_k=4)
        check(
            len(hits) >= 1 and any("배포" in h["text"] for h in hits),
            f"S2 team-notes '배포 절차' 히트 {len(hits)}건(전수 조사 질의 해소)",
        )

        # ── S3: 빈 컬렉션만 배선 → 정직 메시지 ──
        async with SessionLocal() as s:
            emb = (
                await s.execute(select(ModelConfig).where(ModelConfig.name == "mock-embed"))
            ).scalar_one()
            empty = Collection(
                name=f"v437-empty-{uuid.uuid4().hex[:4]}", embedding_model_id=emb.id,
                dims=1024, status="empty",
            )
            s.add(empty)
            await s.commit()
            empty_dict = await _col_dict(s, empty.name)
        tool = rag_runtime.build_rag_tool([empty_dict], [])
        msg = await tool.coroutine(query="아무거나")
        check("문서가 없습니다" in msg and "업로드" in msg, f"S3 빈 컬렉션 정직 메시지 (got {msg[:60]!r})")

        # ── S4: 혼합(빈+채움) → 히트 경로(오탐 방지) ──
        tool2 = rag_runtime.build_rag_tool([empty_dict, col], [])
        msg2 = await tool2.coroutine(query="배포 절차")
        check("문서가 없습니다" not in msg2 and "배포" in msg2,
              f"S4 혼합 배선은 정상 히트 경로 (got {msg2[:50]!r})")
    finally:
        rag_ingest.embed_texts = orig

    print("\n" + ("VERIFY437_OK — 시드 샘플·빈 컬렉션 표면화" if not fails else f"FAIL {len(fails)}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
