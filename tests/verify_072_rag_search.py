"""스펙 072 검증 — RAG retrieval 시험 수단(공유 코어 + `POST /collections/{cid}/search`).

037의 mock-embed 결정성 트릭을 재사용한다: mock 임베딩은 입력 1건당 결정적 벡터 → **저장된 청크와
동일한 텍스트**를 질의로 주면 거리 0 → 유사도 1.000 → 무조건 1위. 두 층을 비겹침으로 단언한다.

  [A] 공유 코어 `runtime.search_collections` (구조화 hit 반환):
    A1 exact-match → score≈1.000 rank1
    A2 score 내림차순 불변
    A3 비-exact score<1, 음수(반-상관) 제외
    A4 top_k=999 → clamp ≤10
    A5 빈 질의 → RagSearchError(kind=empty)
    A6 무매치(빈 컬렉션) → []
    A7 멀티 컬렉션 통합 → exact-match 여전히 rank1
  [B] 엔드포인트 `POST /collections/{cid}/search`:
    B1 정상 → 200, results 구조(score/filename/text), exact rank1
    B2 빈/공백 질의 → 422(스키마 min_length)
    B3 top_k>10 → 422(스키마 le)
    B4 api_key/복호화 비밀 응답 미노출
    B5 없는 컬렉션 → 404

실행: .venv/bin/python tests/verify_072_rag_search.py  (in-process 앱이 127.0.0.1:8000 mock을 침 → dev 서버 필요)
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from api import crypto, runtime  # noqa: E402
from api.auth import _token  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Chunk, Collection, Document, ModelConfig  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
CP = "col_v072_"
MP = "mdl_v072_"

DOC_TEXT = (
    "RAG 시험 엔드포인트 검증 문서입니다. 이 문단은 충분히 길어 작은 청크 크기에서 여러 조각으로 "
    "분할됩니다. 각 조각은 임베딩되어 pgvector에 적재되고 cosine으로 검색됩니다.\n\n"
    "두 번째 문단입니다. 질의는 컬렉션 자신의 임베딩 모델로 임베딩해야 같은 벡터 공간이 됩니다.\n\n"
    "세 번째 문단입니다. 상위 k개 청크를 유사도 내림차순으로 반환하며, 동일 텍스트 질의는 거리 0으로 "
    "정확히 1위가 됩니다. 이것이 결정적 검증의 핵심입니다.\n\n"
    "네 번째 문단입니다. 시험 엔드포인트는 인-챗 도구와 같은 코어를 타므로 drift가 없습니다."
) * 2


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _cleanup() -> None:
    async with SessionLocal() as s:
        col_ids = select(Collection.id).where(Collection.name.like(f"{CP}%"))
        await s.execute(delete(Chunk).where(Chunk.collection_id.in_(col_ids)))
        await s.execute(delete(Document).where(Document.collection_id.in_(col_ids)))
        await s.execute(delete(Collection).where(Collection.name.like(f"{CP}%")))
        await s.execute(delete(ModelConfig).where(ModelConfig.name.like(f"{MP}%")))
        await s.commit()


async def _collection_dict(name: str) -> dict:
    async with SessionLocal() as s:
        c = (
            await s.execute(
                select(Collection)
                .where(Collection.name == name)
                .options(selectinload(Collection.embedding_model).selectinload(ModelConfig.provider))
            )
        ).scalar_one()
        em = c.embedding_model
        ep = em.provider
        return {
            "id": c.id,
            "name": c.name,
            "embed_base_url": ep.base_url,
            "embed_api_key": crypto.decrypt(ep.api_key),
            "embed_model_id": em.model_id,
        }


async def _first_chunk_text(name: str) -> str:
    async with SessionLocal() as s:
        cid = (await s.execute(select(Collection.id).where(Collection.name == name))).scalar_one()
        return (
            await s.execute(
                select(Chunk.text).where(Chunk.collection_id == cid).order_by(Chunk.ordinal).limit(1)
            )
        ).scalar_one()


async def main() -> None:
    await _cleanup()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH, timeout=60) as c:
            provs = (await c.get("/providers")).json()
            mock_p = next((p for p in provs if "_remote" in (p.get("base_url") or "")), None)
            check(mock_p is not None, "mock(_remote) provider 존재")
            mk = await c.post("/models", json={
                "name": f"{MP}embed", "provider_id": mock_p["id"], "model_id": "mock-embed",
                "kind": "embedding", "is_default": False, "params": {},
            })
            check(mk.status_code == 201, f"mock 임베딩 모델 생성 201 (got {mk.status_code})")
            embed_mid = mk.json()["id"]

            for nm in ("main", "empty", "second"):
                cc = await c.post("/collections", json={
                    "name": f"{CP}{nm}", "embedding_model_id": embed_mid,
                    "chunk_size": 200, "chunk_overlap": 20,
                })
                check(cc.status_code == 201, f"컬렉션 {nm} 생성 201 (got {cc.status_code})")
            for nm in ("main", "second"):
                cid = next(x["id"] for x in (await c.get("/collections")).json() if x["name"] == f"{CP}{nm}")
                up = await c.post(f"/collections/{cid}/documents",
                                  files={"file": (f"{nm}.txt", DOC_TEXT.encode("utf-8"), "text/plain")})
                check(up.json()["status"] == "ready", f"{nm} 인제스트 ready")

            col_main = await _collection_dict(f"{CP}main")
            col_empty = await _collection_dict(f"{CP}empty")
            col_second = await _collection_dict(f"{CP}second")
            chunk0 = await _first_chunk_text(f"{CP}main")
            main_id = next(x["id"] for x in (await c.get("/collections")).json() if x["name"] == f"{CP}main")
            empty_id = next(x["id"] for x in (await c.get("/collections")).json() if x["name"] == f"{CP}empty")

            # ============ [A] 공유 코어 search_collections ============
            print("[A] 공유 코어 runtime.search_collections")
            hits = await runtime.search_collections([col_main], chunk0, 4)
            scores = [h["score"] for h in hits]
            check(bool(hits), f"A1 결과 반환 ({len(hits)}건)")
            check(scores and abs(scores[0] - 1.0) < 1e-3, f"A1 exact-match rank1 score≈1.000 (got {scores[:1]})")
            check(all({"score", "filename", "text"} <= set(h) for h in hits), "A1 hit 구조(score/filename/text)")
            check(scores == sorted(scores, reverse=True), f"A2 score 내림차순 (got {scores})")
            check(len(scores) >= 2 and all(s < 1.0 - 1e-9 for s in scores[1:]), f"A3 비-exact score<1 (got {scores})")
            check(all(s >= 0.0 for s in scores), f"A3 음수(반-상관) 제외 (got {scores})")

            big = await runtime.search_collections([col_main], chunk0, 999)
            check(len(big) <= 10, f"A4 top_k=999 clamp ≤10 (got {len(big)})")

            try:
                await runtime.search_collections([col_main], "   ", 4)
                check(False, "A5 빈 질의 RagSearchError 기대했으나 통과")
            except runtime.RagSearchError as exc:
                check(exc.kind == "empty", f"A5 빈 질의 → RagSearchError(kind=empty) (got kind={exc.kind})")

            none_hits = await runtime.search_collections([col_empty], "아무거나 질의", 4)
            check(none_hits == [], f"A6 무매치(빈 컬렉션) → [] (got {none_hits})")

            multi = await runtime.search_collections([col_main, col_second], chunk0, 4)
            ms = [h["score"] for h in multi]
            check(bool(ms) and abs(ms[0] - 1.0) < 1e-3, f"A7 멀티 컬렉션 exact rank1 (got {ms[:1]})")
            check(ms == sorted(ms, reverse=True), "A7 멀티 컬렉션 통합 정렬 유지")

            # ============ [B] 엔드포인트 POST /collections/{cid}/search ============
            print("[B] 엔드포인트 POST /collections/{cid}/search")
            r1 = await c.post(f"/collections/{main_id}/search", json={"query": chunk0, "top_k": 4})
            check(r1.status_code == 200, f"B1 정상 200 (got {r1.status_code})")
            j1 = r1.json()
            check(isinstance(j1.get("results"), list) and bool(j1["results"]), "B1 results 리스트 비어있지 않음")
            top = j1["results"][0]
            check({"score", "filename", "text"} <= set(top), f"B1 결과 구조 (got {list(top)})")
            check(abs(top["score"] - 1.0) < 1e-3, f"B1 exact rank1 score≈1.000 (got {top['score']})")
            check(j1["results"] == sorted(j1["results"], key=lambda h: h["score"], reverse=True),
                  "B1 응답 score 내림차순")

            r2 = await c.post(f"/collections/{main_id}/search", json={"query": "   ", "top_k": 4})
            check(r2.status_code == 422, f"B2 공백 질의 → 422 (got {r2.status_code})")
            r2b = await c.post(f"/collections/{main_id}/search", json={"query": "", "top_k": 4})
            check(r2b.status_code == 422, f"B2 빈 질의 → 422 (got {r2b.status_code})")

            r3 = await c.post(f"/collections/{main_id}/search", json={"query": "x", "top_k": 11})
            check(r3.status_code == 422, f"B3 top_k>10 → 422 (got {r3.status_code})")

            # B4 — 복호화 비밀 미노출: mock provider api_key(복호화값)가 응답 본문에 없어야.
            secret = col_main["embed_api_key"]
            check(secret and secret not in r1.text and "api_key" not in r1.text,
                  "B4 복호화 api_key/필드 응답 미노출")

            # B5 — 없는 컬렉션 → 404
            import uuid as _uuid
            ghost = _uuid.uuid4()
            r5 = await c.post(f"/collections/{ghost}/search", json={"query": "x", "top_k": 4})
            check(r5.status_code == 404, f"B5 없는 컬렉션 → 404 (got {r5.status_code})")
            _ = empty_id  # (참조 — 빈 컬렉션은 A6에서 사용)

            # B6 — query 길이 상한(적대 리뷰 072 P2): max_length 초과 → 422(자원 점유 차단).
            r6 = await c.post(f"/collections/{main_id}/search", json={"query": "가" * 4001, "top_k": 4})
            check(r6.status_code == 422, f"B6 거대 query(>4000) → 422 (got {r6.status_code})")
            r6b = await c.post(f"/collections/{main_id}/search", json={"query": "가" * 4000, "top_k": 4})
            check(r6b.status_code == 200, f"B6 경계 query(=4000) → 200 (got {r6b.status_code})")

            # B7 — kind 가드(적대 리뷰 072 P2): 컬렉션 참조 모델을 chat으로 바꾸면 502가 아니라 400.
            mp = next(p for p in provs if p["id"] == mock_p["id"])
            up7 = await c.put(f"/models/{embed_mid}", json={
                "name": f"{MP}embed", "provider_id": mp["id"], "model_id": "mock-embed",
                "kind": "chat", "is_default": False, "params": {},
            })
            check(up7.status_code == 200, f"B7 준비: 모델 kind→chat 변경 (got {up7.status_code})")
            r7 = await c.post(f"/collections/{main_id}/search", json={"query": "질의", "top_k": 4})
            check(r7.status_code == 400, f"B7 chat 모델 컬렉션 검색 → 400(502 아님) (got {r7.status_code})")
    finally:
        await _cleanup()


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")
