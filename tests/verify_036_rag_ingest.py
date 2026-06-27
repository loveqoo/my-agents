"""스펙 036 검증 — RAG 인제스트(컬렉션 + 문서 업로드 → 청킹 → 임베딩 → pgvector).

인프로세스 httpx(ASGI) + 실 DB로 수치/불변식 단언. 검증용 모델·컬렉션을 고유 prefix
(mdl_v036_/col_v036_)로 만들어 단언 후 **삭제**(자가정리, 실데이터 불간섭).

happy-path는 **mock 임베딩 모델**(Mock LLM provider, `/_remote/v1/embeddings`가 입력 1건당
RAG_EMBED_DIMS 벡터 1개 반환)로 라이브 MLX 없이 결정적으로 돈다. (in-process 앱이 outbound로
127.0.0.1:8000 mock을 치므로 dev 서버가 떠 있어야 한다.)

단언:
  1. 차원 가드 순수 헬퍼 _dim_mismatch: (8,1024)→사유, (1024,1024)→None, (None,1024)→None.
  2. 생성 검증 음성: 없는 모델 id→400, chat-kind 모델→400.
  3. happy-path 인제스트: 컬렉션 생성(dims=1024) → 멀티청크 텍스트 업로드 → status=ready,
     chunk_count>1, DB rag_chunks 수 일치, 각 임베딩 차원==1024.
  4. 가드2(인제스트 차원 불일치): collection.dims를 999로 비틀고 업로드 → status=error,
     사유에 '차원', 청크 0(적재 중단).
  5. 가드3(health): 정상 컬렉션 consistent=True(db/collection/model 1024 3자 일치),
     dims=999 컬렉션 consistent=False.
  6. CASCADE: 문서 삭제→그 청크 0·컬렉션 카운트 감소, 컬렉션 삭제→문서·청크 전멸.

실행: .venv/bin/python tests/verify_036_rag_ingest.py
"""
import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from api.auth import _token  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Chunk, Collection, Document, ModelConfig, Provider  # noqa: E402
from api.rag import _dim_mismatch  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
CP = "col_v036_"
MP = "mdl_v036_"

# 멀티청크를 강제하는 본문(chunk_size=200/overlap=20 → 여러 청크). 문단 구분 포함.
DOC_TEXT = (
    "RAG 인제스트 검증 문서입니다. 이 문단은 충분히 길어서 작은 청크 크기에서 여러 조각으로 "
    "분할됩니다. 각 조각은 임베딩되어 pgvector에 적재됩니다.\n\n"
    "두 번째 문단입니다. 청킹 전략은 컬렉션별로 설정할 수 있으며 기본은 1000자/200 오버랩이지만 "
    "이 검증에서는 작은 값으로 다중 청크를 만듭니다. 차원 트랩 대응이 핵심입니다.\n\n"
    "세 번째 문단입니다. 임베딩 차원은 저장소(rag_chunks vector(N))와 정확히 일치해야 하며, "
    "불일치 시 인제스트가 중단되고 문서 상태가 error로 보존됩니다. 조용한 죽음은 없습니다.\n\n"
    "네 번째 문단입니다. CASCADE 삭제로 컬렉션을 지우면 문서와 청크가 함께 사라집니다. "
    "집계 캐시(doc_count/chunk_count)도 정합을 유지합니다."
) * 2


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _cleanup() -> None:
    async with SessionLocal() as s:
        # 벌크 SQL 삭제(FK 안전 순서: 청크→문서→컬렉션→모델). ORM cascade의 동기 lazy-load 회피.
        col_ids = select(Collection.id).where(Collection.name.like(f"{CP}%"))
        await s.execute(delete(Chunk).where(Chunk.collection_id.in_(col_ids)))
        await s.execute(delete(Document).where(Document.collection_id.in_(col_ids)))
        await s.execute(delete(Collection).where(Collection.name.like(f"{CP}%")))
        await s.execute(delete(ModelConfig).where(ModelConfig.name.like(f"{MP}%")))  # 컬렉션 제거 후라 RESTRICT 해제
        await s.commit()


async def _count(model, **filt) -> int:
    async with SessionLocal() as s:
        q = select(func.count()).select_from(model)
        for k, v in filt.items():
            q = q.where(getattr(model, k) == v)
        return (await s.scalar(q)) or 0


async def main() -> None:
    await _cleanup()

    # --- 1. 순수 헬퍼 단위 ---
    print("[unit] _dim_mismatch 차원 가드")
    check(_dim_mismatch(8, 1024) is not None, "(8,1024)→사유")
    check(_dim_mismatch(1024, 1024) is None, "(1024,1024)→None")
    check(_dim_mismatch(None, 1024) is None, "(None,1024)→None(probe 실패는 통과)")

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH, timeout=60) as c:
            # mock 임베딩 모델 준비(self-contained) — Mock LLM provider 아래 embedding 모델.
            provs = (await c.get("/providers")).json()
            # mock provider는 self-call(_remote/v1) base_url로 식별(이름은 035 마이그레이션이 netloc 파생).
            mock_p = next((p for p in provs if "_remote" in (p.get("base_url") or "")), None)
            check(mock_p is not None, "mock(_remote) provider 존재")
            chat_m = (await c.get("/models")).json()
            mock_chat = next((m for m in chat_m if m["kind"] == "chat" and "mock" in m["name"].lower()), None)
            mk = (await c.post("/models", json={
                "name": f"{MP}embed", "provider_id": mock_p["id"], "model_id": "mock-embed",
                "kind": "embedding", "is_default": False, "params": {},
            }))
            check(mk.status_code == 201, f"mock 임베딩 모델 생성 201 (got {mk.status_code})")
            embed_mid = mk.json()["id"]

            # --- 2. 생성 검증 음성 ---
            print("[create] 검증 음성(없는 모델 / chat-kind)")
            r = await c.post("/collections", json={"name": f"{CP}bad1", "embedding_model_id": str(uuid.uuid4())})
            check(r.status_code == 400, f"없는 임베딩 모델 → 400 (got {r.status_code})")
            if mock_chat:
                r = await c.post("/collections", json={"name": f"{CP}bad2", "embedding_model_id": mock_chat["id"]})
                check(r.status_code == 400, f"chat-kind 모델 → 400 (got {r.status_code})")
            # 청킹 경계 검증(스키마 bound) — chunk_size=0은 1자 청크 폭주 위험 → 422.
            r = await c.post("/collections", json={
                "name": f"{CP}bad3", "embedding_model_id": embed_mid, "chunk_size": 0,
            })
            check(r.status_code == 422, f"chunk_size=0 → 422 (got {r.status_code})")

            # --- 3. happy-path 인제스트 ---
            print("[ingest] happy-path 멀티청크 적재")
            cc = await c.post("/collections", json={
                "name": f"{CP}main", "description": "검증", "embedding_model_id": embed_mid,
                "chunk_size": 200, "chunk_overlap": 20,
            })
            check(cc.status_code == 201, f"컬렉션 생성 201 (got {cc.status_code} {cc.text[:120]})")
            col = cc.json()
            cid = col["id"]
            check(col["dims"] == 1024, f"dims=1024 박제 (got {col['dims']})")
            check(col["status"] == "empty", "초기 status=empty")

            up = await c.post(f"/collections/{cid}/documents",
                              files={"file": ("doc.txt", DOC_TEXT.encode("utf-8"), "text/plain")})
            check(up.status_code == 201, f"문서 업로드 201 (got {up.status_code} {up.text[:160]})")
            doc = up.json()
            did = doc["id"]
            n = doc["chunk_count"]
            check(doc["status"] == "ready", f"문서 status=ready (got {doc['status']}, err={doc.get('error')})")
            check(n > 1, f"멀티청크 생성 (chunk_count={n})")

            # 컬렉션 카운트 정합
            colg = (await c.get(f"/collections/{cid}")).json()
            check(colg["doc_count"] == 1, f"doc_count=1 (got {colg['doc_count']})")
            check(colg["chunk_count"] == n, f"chunk_count={n} (got {colg['chunk_count']})")
            check(colg["status"] == "ready", "컬렉션 status=ready")

            # DB: rag_chunks 수 + 임베딩 차원
            db_n = await _count(Chunk, collection_id=uuid.UUID(cid))
            check(db_n == n, f"DB rag_chunks 수=={n} (got {db_n})")
            async with SessionLocal() as s:
                ch = (await s.execute(select(Chunk).where(Chunk.collection_id == uuid.UUID(cid)).limit(1))).scalar_one()
                check(len(ch.embedding) == 1024, f"임베딩 차원==1024 (got {len(ch.embedding)})")

            # --- 4. 가드2: 인제스트 차원 불일치 ---
            print("[guard2] 인제스트 차원 불일치 → error")
            cc2 = await c.post("/collections", json={
                "name": f"{CP}drift", "embedding_model_id": embed_mid, "chunk_size": 200, "chunk_overlap": 20,
            })
            cid2 = cc2.json()["id"]
            async with SessionLocal() as s:  # collection.dims를 999로 비틀어 모델 drift 모사
                cdb = await s.get(Collection, uuid.UUID(cid2))
                cdb.dims = 999
                await s.commit()
            up2 = await c.post(f"/collections/{cid2}/documents",
                               files={"file": ("d.txt", DOC_TEXT.encode("utf-8"), "text/plain")})
            d2 = up2.json()
            check(d2["status"] == "error", f"차원 불일치 → status=error (got {d2['status']})")
            check("차원" in (d2.get("error") or ""), f"error에 사유 보존 (got {d2.get('error')})")
            check(await _count(Chunk, document_id=uuid.UUID(d2["id"])) == 0, "적재 중단 — 청크 0")

            # --- 5. 가드3: health ---
            print("[guard3] health 차원 정합")
            h1 = (await c.get(f"/collections/{cid}/health")).json()
            check(h1["consistent"] is True, f"정상 컬렉션 consistent=True (detail={h1['detail']})")
            check(h1["db_dims"] == 1024 and h1["collection_dims"] == 1024 and h1["model_dims"] == 1024,
                  f"3자 1024 일치 (got {h1['db_dims']}/{h1['collection_dims']}/{h1['model_dims']})")
            h2 = (await c.get(f"/collections/{cid2}/health")).json()
            check(h2["consistent"] is False, "dims=999 컬렉션 consistent=False")
            check(h2["collection_dims"] == 999 and h2["db_dims"] == 1024, "health가 drift 노출(999 vs 1024)")

            # --- 6. CASCADE ---
            print("[cascade] 문서·컬렉션 삭제 전파")
            dd = await c.delete(f"/collections/{cid}/documents/{did}")
            check(dd.status_code == 204, f"문서 삭제 204 (got {dd.status_code})")
            check(await _count(Chunk, document_id=uuid.UUID(did)) == 0, "문서 청크 CASCADE 삭제")
            colg2 = (await c.get(f"/collections/{cid}")).json()
            check(colg2["doc_count"] == 0 and colg2["chunk_count"] == 0, "카운트 0으로 감소")
            check(colg2["status"] == "empty", "마지막 문서 삭제 후 status=empty")

            # 재인제스트 후 컬렉션 통째 삭제 → 전멸
            await c.post(f"/collections/{cid}/documents",
                         files={"file": ("d2.txt", DOC_TEXT.encode("utf-8"), "text/plain")})
            dc = await c.delete(f"/collections/{cid}")
            check(dc.status_code == 204, f"컬렉션 삭제 204 (got {dc.status_code})")
            check(await _count(Document, collection_id=uuid.UUID(cid)) == 0, "컬렉션 문서 전멸")
            check(await _count(Chunk, collection_id=uuid.UUID(cid)) == 0, "컬렉션 청크 전멸")
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
