"""스펙 048 검증 — RAG 임베딩 게이트 + 샘플 적재(#9).

두 가지 새 계약을 단언한다(나머지 인제스트/retrieval 정합은 036/037이 이미 커버):

  A. 게이트 단위 시맨틱(seed._collection_seed_specs) — DB 없이 순수 검증.
     "임베딩 모델 설정이 있는 경우만"이라는 사용자 원칙을 코드가 지키는지.
       A1. embs=[] → [] (모델 없으면 컬렉션 시드 스킵)
       A2. 이름 매칭 → 그 모델에 바인딩(docs_kb→mock-embed)
       A3. 이름 불매칭(None) → 기본(is_default) 모델로 폴백
       A4. 기본 플래그가 없으면 첫 번째로 폴백
  B. 실제 번들 샘플(data/rag_samples/*.md)의 self-fixtured 적재 + 검색 결정성.
     037은 합성 문서를 쓰지만, 여기서는 *실제 출하되는 샘플 파일*이 인제스트되어 검색 1위로
     돌아오는지를 단언 — #9 산출물(populated docs_kb)의 통합 증거. 고유 prefix(col_v048_/
     mdl_v048_)로 데모 시드와 디커플(learning 045).
       B1. 각 샘플 .md 업로드 → 201 + status=ready + chunk_count>0
       B2. 컬렉션 dims=1024(RAG_EMBED_DIMS) 고정
       B3. 저장된 첫 청크 텍스트 질의 → 1위 유사도 1.000(결정적 mock 벡터)

실행: .venv/bin/python tests/verify_048_sample_ingest.py  (in-process 앱이 :8000 mock을 침 → dev 서버 필요)
"""
import asyncio
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from api import crypto, runtime, seed  # noqa: E402
from api.auth import _token  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import RAG_EMBED_DIMS, Chunk, Collection, Document, ModelConfig  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
CP = "col_v048_"
MP = "mdl_v048_"
SAMPLES_DIR = os.path.join(ROOT, "packages", "api", "data", "rag_samples")


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ── 게이트 단위 검증용 가짜 임베딩 모델(.name/.is_default/.id만 필요) ──────────
class _FakeEmb:
    def __init__(self, name: str, is_default: bool, mid: str, kind: str = "embedding"):
        self.name = name
        self.is_default = is_default
        self.id = mid
        self.kind = kind


def _gate_tests() -> None:
    print("── A. 게이트 단위 시맨틱(seed._collection_seed_specs) ──")
    # A1: 모델 없음 → 빈 리스트
    check(seed._collection_seed_specs([]) == [], "A1 embs=[] → [] (컬렉션 시드 스킵)")

    cols = [
        ("docs_kb", "d1", "mock-embed"),
        ("product_titles", "d2", None),
    ]
    mock = _FakeEmb("mock-embed", False, "ID_MOCK")
    e5 = _FakeEmb("multilingual-e5-large", True, "ID_E5")
    specs = seed._collection_seed_specs([mock, e5], cols)
    by = {n: mid for n, _d, mid in specs}
    # A2: docs_kb는 이름 매칭으로 mock-embed
    check(by.get("docs_kb") == "ID_MOCK", "A2 이름 매칭 → docs_kb=mock-embed")
    # A3: product_titles(None)는 기본(is_default=True)인 e5로 폴백
    check(by.get("product_titles") == "ID_E5", "A3 불매칭(None) → 기본(e5)로 폴백")
    # A4: 기본 플래그 없으면 첫 번째로 폴백
    a = _FakeEmb("a", False, "ID_A")
    b = _FakeEmb("b", False, "ID_B")
    specs2 = seed._collection_seed_specs([a, b], [("x", "dx", None)])
    check(specs2[0][2] == "ID_A", "A4 기본 없음 → 첫 번째(a)로 폴백")
    check(len(specs) == len(cols), "게이트 통과 시 전체 컬렉션 스펙 반환")
    # A5: chat 모델이 섞여 들어와도 헬퍼가 제외 → embedding만 후보(적대 리뷰 048 #4)
    chat = _FakeEmb("some-chat", True, "ID_CHAT", kind="chat")
    specs3 = seed._collection_seed_specs([chat, mock], [("docs_kb", "d", None)])
    check(specs3 and specs3[0][2] == "ID_MOCK", "A5 chat 모델 제외 → embedding(mock)에만 바인딩")
    check(seed._collection_seed_specs([chat], [("x", "d", None)]) == [], "A5b chat만 있으면 [] (게이트 막힘)")


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


async def _first_chunk_text(cid) -> str:
    async with SessionLocal() as s:
        return (
            await s.execute(
                select(Chunk.text).where(Chunk.collection_id == cid).order_by(Chunk.ordinal).limit(1)
            )
        ).scalar_one()


def _sims(out: str) -> list[float]:
    return [float(x) for x in re.findall(r"유사도 (-?[\d.]+)\)", out)]


def _load_samples() -> list[tuple[str, bytes]]:
    out = []
    for fn in sorted(os.listdir(SAMPLES_DIR)):
        if fn.endswith((".md", ".txt")):
            with open(os.path.join(SAMPLES_DIR, fn), "rb") as f:
                out.append((fn, f.read()))
    return out


async def main() -> None:
    _gate_tests()
    print("── B. 실제 번들 샘플 self-fixtured 적재 + 검색 ──")
    samples = _load_samples()
    check(len(samples) >= 1, f"번들 샘플 파일 발견({len(samples)}개)")

    await _cleanup()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH, timeout=120) as c:
            provs = (await c.get("/providers")).json()
            mock_p = next((p for p in provs if "_remote" in (p.get("base_url") or "")), None)
            check(mock_p is not None, "mock(_remote) provider 존재")
            mk = await c.post("/models", json={
                "name": f"{MP}embed", "provider_id": mock_p["id"], "model_id": "mock-embed",
                "kind": "embedding", "is_default": False, "params": {},
            })
            check(mk.status_code == 201, f"mock 임베딩 모델 생성 201 (got {mk.status_code})")
            embed_mid = mk.json()["id"]

            # 서버측 게이트 잠금(적대 리뷰 048 #2): 컬렉션 생성은 *유효한 embedding 모델 id*가
            # 있어야만 통과한다 → 임베딩 모델이 0개면 줄 수 있는 유효 id가 없어 항상 400.
            # 그 메커니즘을 직접 단언: chat 모델 id·존재하지 않는 id로는 400.
            chat_models = [m for m in (await c.get("/models")).json() if m.get("kind") == "chat"]
            if chat_models:
                bad = await c.post("/collections", json={
                    "name": f"{CP}badchat", "embedding_model_id": chat_models[0]["id"],
                    "chunk_size": 1000, "chunk_overlap": 200,
                })
                check(bad.status_code == 400, f"게이트: chat 모델로 컬렉션 생성 → 400 (got {bad.status_code})")
            ghost = await c.post("/collections", json={
                "name": f"{CP}ghost", "embedding_model_id": "00000000-0000-0000-0000-000000000000",
                "chunk_size": 1000, "chunk_overlap": 200,
            })
            check(ghost.status_code in (400, 404, 422), f"게이트: 존재하지 않는 모델 id → 4xx (got {ghost.status_code})")

            cc = await c.post("/collections", json={
                "name": f"{CP}docs", "embedding_model_id": embed_mid,
                "chunk_size": 1000, "chunk_overlap": 200,
            })
            check(cc.status_code == 201, f"컬렉션 생성 201 (got {cc.status_code})")
            col = cc.json()
            col_id = col["id"]
            # B2: 차원 고정
            check(col["dims"] == RAG_EMBED_DIMS, f"B2 컬렉션 dims={RAG_EMBED_DIMS} 고정 (got {col['dims']})")

            # B1: 각 샘플 업로드 → ready + chunks>0
            total_chunks = 0
            for fn, data in samples:
                up = await c.post(
                    f"/collections/{col_id}/documents",
                    files={"file": (fn, data, "text/markdown")},
                )
                body = up.json()
                ok = up.status_code == 201 and body.get("status") == "ready" and (body.get("chunk_count") or 0) > 0
                total_chunks += body.get("chunk_count") or 0
                check(ok, f"B1 {fn}: 201+ready+chunks>0 (got {up.status_code}/{body.get('status')}/{body.get('chunk_count')})")

        # B3: 저장된 첫 청크 텍스트 질의 → 1위 유사도 1.000(결정적)
        async with SessionLocal() as s:
            cid = (await s.execute(select(Collection.id).where(Collection.name == f"{CP}docs"))).scalar_one()
            db_chunks = await s.scalar(select(func.count()).select_from(Chunk).where(Chunk.collection_id == cid))
        check(db_chunks == total_chunks, f"DB 청크수={db_chunks} == 업로드 합계={total_chunks}")

        chunk0 = await _first_chunk_text(cid)
        cdict = await _collection_dict(f"{CP}docs")
        sink: list[dict] = []
        tool = runtime.build_rag_tool([cdict], sink)
        out = await tool.ainvoke({"query": chunk0, "top_k": 3})
        sims = _sims(out)
        snippet = chunk0.strip().replace("\n", " ")[:24]
        check(bool(sims) and abs(sims[0] - 1.000) < 1e-3, f"B3 1위 유사도 1.000(결정적) (got {sims[:1]})")
        check(snippet in out, "B3 1위에 질의 청크 본문 포함")
        check(sink and sink[-1].get("hits", 0) >= 1, "B3 calls_sink hits>=1")

        # B4: 컬렉션이 참조 중인 임베딩 모델 삭제 시도 → 깔끔한 409(IntegrityError 500 아님, 적대 리뷰 048 #1)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH, timeout=30) as c2:
            dele = await c2.delete(f"/models/{embed_mid}")
            check(dele.status_code == 409, f"B4 참조 중 임베딩 모델 삭제 → 409(500 아님) (got {dele.status_code})")
    finally:
        await _cleanup()

    print()
    if _fails:
        print(f"❌ {len(_fails)}건 실패")
        for m in _fails:
            print("   - " + m)
        sys.exit(1)
    print("✅ 048 전체 통과 — 게이트 시맨틱 + 실제 샘플 적재/검색 결정성")


if __name__ == "__main__":
    asyncio.run(main())
