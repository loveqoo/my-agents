"""스펙 037 검증 — RAG retrieval(질의 임베딩 → pgvector cosine 검색 → 도구 반환).

036 인제스트 위에서 retrieval 도구(`runtime.build_rag_tool`)의 수치/불변식을 인프로세스로 단언한다.
검증용 모델·컬렉션을 고유 prefix(mdl_v037_/col_v037_)로 만들어 단언 후 **삭제**(자가정리).

결정적 핵심 트릭: mock 임베딩은 입력 1건당 결정적 벡터를 반환한다. 따라서 **저장된 청크와 정확히
동일한 텍스트**를 질의로 주면 동일 벡터 → cosine 거리 0 → 유사도 1.000 → 무조건 1위. mock의
의미성에 의존하지 않고 검색 정합(임베딩·정렬·반환)을 단언할 수 있다.

단언:
  1. exact-match: 저장된 청크 텍스트를 질의 → 1위에 그 청크 + 유사도 1.000 + calls_sink ok.
  2. 정렬 불변식: 반환 유사도가 비증가(내림차순) = dist 오름차순.
  3. 빈 질의 → graceful 안내 + calls_sink status=error(크래시 0).
  4. 무매치(빈 컬렉션) → "관련 문서를 찾지 못했습니다." + hits 0.
  5. top_k 클램프: top_k=999 → 크래시 0, hits<=10.
  6. 멀티 컬렉션 통합: 두 컬렉션에 걸쳐 검색 → exact-match 청크 여전히 1위.
  7. 임베딩 실패 graceful: 잘못된 base_url → "문서 검색 실패..." + calls_sink status=error.

실행: .venv/bin/python tests/verify_037_rag_retrieval.py  (in-process 앱이 127.0.0.1:8000 mock을 침 → dev 서버 필요)
"""
import asyncio
import os
import re
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from api import crypto, runtime  # noqa: E402
from api.auth import _token  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Chunk, Collection, Document, ModelConfig, Provider  # noqa: E402,F401

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
CP = "col_v037_"
MP = "mdl_v037_"

DOC_TEXT = (
    "RAG retrieval 검증 문서입니다. 이 문단은 충분히 길어 작은 청크 크기에서 여러 조각으로 "
    "분할됩니다. 각 조각은 임베딩되어 pgvector에 적재되고 cosine으로 검색됩니다.\n\n"
    "두 번째 문단입니다. 질의는 컬렉션 자신의 임베딩 모델로 임베딩해야 같은 벡터 공간이 됩니다. "
    "모델이 다르면 검색이 무의미합니다.\n\n"
    "세 번째 문단입니다. 상위 k개 청크를 유사도 내림차순으로 반환하며, 동일 텍스트 질의는 거리 0으로 "
    "정확히 1위가 됩니다. 이것이 결정적 검증의 핵심입니다.\n\n"
    "네 번째 문단입니다. 여러 컬렉션에 걸친 검색은 통합 정렬됩니다. 실패는 에이전트를 죽이지 않고 "
    "graceful 메시지로 흡수됩니다."
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
    """_load_context와 같은 규칙으로 컬렉션을 검색 도구용 dict로 해석(복호화 포함)."""
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


async def _chunk_count(name: str) -> int:
    from sqlalchemy import func
    async with SessionLocal() as s:
        cid = (await s.execute(select(Collection.id).where(Collection.name == name))).scalar_one()
        return await s.scalar(select(func.count()).select_from(Chunk).where(Chunk.collection_id == cid))


def _sims(out: str) -> list[float]:
    # 포맷 토큰 "유사도 1.000)"만 캡처 — 닫는 괄호로 앵커. 청크 본문(스니펫)이 "유사도"·숫자를
    # 포함해도 오염되지 않게(이 검증 DOC 자체가 '유사도 내림차순' 문구를 담고 있다).
    # 음수 부호 필수(-?): cosine 유사도 1-d 는 비유사 청크에서 음수가 된다(예 -0.048). 부호를
    # 빼면 음수 라인이 통째로 누락돼 반환 건수를 과소집계한다 — 과거 HNSW starvation 오진의 원인.
    return [float(x) for x in re.findall(r"유사도 (-?[\d.]+)\)", out)]


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

            # 컬렉션 A(문서 적재) + 컬렉션 B(빈) + 컬렉션 C(문서 적재, 멀티 컬렉션용)
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

            # --- 1. exact-match: 저장된 청크 텍스트 질의 → 1위 + 유사도 1.000 ---
            print("[1] exact-match retrieval")
            chunk0 = await _first_chunk_text(f"{CP}main")
            sink: list[dict] = []
            tool = runtime.build_rag_tool([col_main], sink)
            out = await tool.ainvoke({"query": chunk0, "top_k": 4})
            sims = _sims(out)
            check(bool(sims), f"결과 반환됨 (out={out[:80]!r})")
            check(sims and abs(sims[0] - 1.0) < 1e-3, f"1위 유사도≈1.000 (got {sims[:1]})")
            head = chunk0.strip().replace("\n", " ")[:24]
            check(head in out, "1위 라인에 동일 청크 텍스트 포함")
            check(sink and sink[-1]["server"] == "rag" and sink[-1]["status"] == "ok" and sink[-1]["hits"] >= 1,
                  f"calls_sink ok 기록 (got {sink[-1:] })")
            # 변별: mock이 입력 의존 벡터를 주므로 exact-match(1.000)는 다른 청크(<1)보다 엄격히 위.
            # (상수 벡터였다면 전부 1.000이라 이 단언이 retrieval 랭킹을 증명하지 못한다 — learning 035.)
            check(len(sims) >= 2 and sims[0] > sims[1] + 1e-6,
                  f"변별: 1위(exact) > 2위 (got {sims[:2]})")
            check(all(s < 1.0 - 1e-9 for s in sims[1:]), f"비-exact 청크는 유사도<1 (got {sims})")
            # 음수 유사도 floor(타자검증): 반-상관 청크는 근거가 아니므로 반환에서 제외 → 전부 >=0.
            check(all(s >= 0.0 for s in sims), f"음수 유사도(반-상관) 제외 (got {sims})")

            # --- 2. 정렬 불변식: 유사도 비증가 ---
            print("[2] 정렬 불변식(유사도 내림차순)")
            check(sims == sorted(sims, reverse=True), f"유사도 비증가 (got {sims})")

            # --- 3. 빈 질의 graceful ---
            print("[3] 빈 질의 graceful")
            sink3: list[dict] = []
            t3 = runtime.build_rag_tool([col_main], sink3)
            o3 = await t3.ainvoke({"query": "   ", "top_k": 4})
            check("비어" in o3, f"빈 질의 안내 (got {o3!r})")
            check(sink3 and sink3[-1]["status"] == "error", "빈 질의 calls_sink status=error")

            # --- 4. 무매치(빈 컬렉션) ---
            print("[4] 무매치(빈 컬렉션)")
            sink4: list[dict] = []
            t4 = runtime.build_rag_tool([col_empty], sink4)
            o4 = await t4.ainvoke({"query": "아무거나 질의", "top_k": 4})
            check("찾지 못" in o4, f"무매치 안내 (got {o4!r})")
            check(sink4 and sink4[-1]["hits"] == 0 and sink4[-1]["status"] == "ok", "무매치 hits=0 ok")

            # --- 5. top_k 클램프 + floor 내 전건 반환(starvation 없음) ---
            print("[5] top_k 클램프 + floor 내 전건 반환")
            sink5: list[dict] = []
            t5 = runtime.build_rag_tool([col_main], sink5)
            o5 = await t5.ainvoke({"query": chunk0, "top_k": 999})
            sims5 = _sims(o5)
            n5 = len(sims5)
            main_n = await _chunk_count(f"{CP}main")
            check(n5 <= 10, f"top_k 상한 10 클램프 (got {n5})")
            # floor(>=0) 적용 후 양수 유사도 청크는 빠짐없이 반환 — HNSW 후필터 starvation이 없음을 단언.
            # main_n(<10)개 중 음수 유사도분만 빠지므로 0<n5<=main_n, 그리고 반환은 전부 >=0이어야 한다.
            check(0 < n5 <= main_n and all(s >= 0.0 for s in sims5),
                  f"floor 내 양수 청크 전건·전부>=0 (main {main_n} → {n5}건, sims {sims5})")
            check(abs(sims5[0] - 1.0) < 1e-3, f"클램프 후에도 exact-match 1위 1.000 (got {sims5[:1]})")

            # --- 6. 멀티 컬렉션 통합 ---
            print("[6] 멀티 컬렉션 통합 정렬")
            sink6: list[dict] = []
            t6 = runtime.build_rag_tool([col_main, col_second], sink6)
            o6 = await t6.ainvoke({"query": chunk0, "top_k": 4})
            s6 = _sims(o6)
            check(bool(s6) and abs(s6[0] - 1.0) < 1e-3, f"멀티 컬렉션서 exact-match 여전히 1위 (got {s6[:1]})")
            check(s6 == sorted(s6, reverse=True), "멀티 컬렉션 통합 정렬 유지")

            # --- 7. 임베딩 실패 graceful ---
            print("[7] 임베딩 실패 graceful")
            bad = dict(col_main)
            bad["embed_base_url"] = "http://127.0.0.1:1/nope"  # 도달 불가
            sink7: list[dict] = []
            t7 = runtime.build_rag_tool([bad], sink7)
            o7 = await t7.ainvoke({"query": "질의", "top_k": 4})
            check("실패" in o7, f"임베딩 실패 graceful (got {o7!r})")
            check(sink7 and sink7[-1]["status"] == "error", "임베딩 실패 calls_sink status=error")
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
