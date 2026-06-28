"""RAG 대표 컬렉션(docs_kb) 샘플 적재 — 멱등(스펙 048 #9).

#9: 어드민 테스트에서 컬렉션이 전부 비어 "고장처럼" 보였다. 대표 컬렉션 하나를 *결정적으로*
채워 검색 동작까지 보이게 한다. 라이브 MLX에 의존하지 않도록 docs_kb를 mock-embed(스펙 024,
`/_remote/v1/embeddings`가 RAG_EMBED_DIMS=1024 결정적 벡터 반환)에 바인딩해 적재한다.

동작:
  1. (게이트) embedding 모델 mock-embed가 없으면 스킵 — "임베딩 모델 설정이 있는 경우만 적재".
  2. docs_kb가 mock-embed에 안 묶여 있고 아직 비었으면 재바인딩(차원 동일 1024 → 안전).
  3. (멱등) doc_count>0이면 이미 적재됨 → 스킵.
  4. data/rag_samples/*.md를 실 인제스트 엔드포인트로 적재(extract→chunk→embed→pgvector 전 경로).
  5. 검색 1회(runtime.build_rag_tool)로 동작 확인 — 샘플 청크 텍스트 질의 → 1위 유사도≈1.000.

전제: 마이그레이션 적용된 DB + 라이브 서버(127.0.0.1:8000)가 mock `/_remote/v1/embeddings` 응답.
실행: cd packages/api && uv run python scripts/ingest_rag_samples.py
"""

import asyncio
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, _SRC)

import httpx  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from api import crypto, runtime  # noqa: E402
from api.auth import _token  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Chunk, Collection, ModelConfig  # noqa: E402,F401

_AUTH = {"Authorization": f"Bearer {_token()}"}
TARGET = os.environ.get("RAG_SAMPLE_COLLECTION", "docs_kb")
EMBED_MODEL = "mock-embed"  # 라이브 비의존·결정적
# populated 상태를 정직하게 반영하는 설명(seed.py와 동일 문구) — 적재됐는데 "업로드해 채우세요"라
# 말하면 #9 정직화 취지에 어긋난다. 어느 경로든 이 문구로 자가치유한다.
TARGET_DESC = "헬프센터 문서 본문 지식베이스 — RAG 답변에 사용(샘플 적재됨, 스펙 048)."
SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_samples"
)


def _load_samples() -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for fn in sorted(os.listdir(SAMPLES_DIR)):
        if fn.endswith((".md", ".txt")):
            with open(os.path.join(SAMPLES_DIR, fn), "rb") as f:
                out.append((fn, f.read()))
    return out


async def _ensure_binding() -> tuple[str | None, str]:
    """docs_kb를 mock-embed에 바인딩 보장. 반환 (collection_id|None, 사유).

    col_id를 돌려주면 main()이 *파일명 단위 멱등*으로 적재한다(doc_count 게이트 아님 — 적대 리뷰
    048: doc_count는 성공분만 세는 캐시라 부분 실패를 'populated'로 오인한다). None이면 적재 스킵.
    비어있거나 이미 mock-embed면 바인딩, 비어있지 않은데 *다른* 모델이면 벡터공간 보존 위해 스킵.
    """
    async with SessionLocal() as s:
        col = (
            await s.execute(select(Collection).where(Collection.name == TARGET))
        ).scalar_one_or_none()
        if col is None:
            return None, f"컬렉션 '{TARGET}' 없음(임베딩 모델 미설정으로 시드 스킵됐을 수 있음)"
        mock = (
            await s.execute(select(ModelConfig).where(ModelConfig.name == EMBED_MODEL))
        ).scalar_one_or_none()
        if mock is None:
            return None, f"임베딩 모델 '{EMBED_MODEL}' 없음 → 게이트로 적재 스킵"
        col_id = str(col.id)
        doc_count = col.doc_count
        is_mock = col.embedding_model_id == mock.id
        # 설명 자가치유: populated 데모 컬렉션이 옛 "업로드해 채우세요" 문구를 달고 있으면 교정.
        if col.description != TARGET_DESC:
            col.description = TARGET_DESC
            await s.commit()
        if is_mock:
            return col_id, "already-mock-embed"
        if doc_count > 0:
            # 다른 모델로 이미 적재됨 → mock으로 재바인딩하면 기존 벡터와 질의 벡터 공간이 어긋난다.
            return None, f"'{TARGET}'이 다른 모델로 이미 적재됨(doc_count={doc_count}) — 벡터공간 보존 위해 스킵"
        # 비어 있으니 안전하게 mock으로 재바인딩(차원 동일 1024).
        async with SessionLocal() as s2:
            c2 = (await s2.execute(select(Collection).where(Collection.id == col.id))).scalar_one()
            c2.embedding_model_id = mock.id
            await s2.commit()
        return col_id, "rebound-to-mock-embed"


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
                select(Chunk.text)
                .where(Chunk.collection_id == cid)
                .order_by(Chunk.ordinal, Chunk.id)  # ordinal은 문서마다 0부터 → id로 결정적 tiebreak(적대 리뷰 048)
                .limit(1)
            )
        ).scalar_one()


async def main() -> int:
    col_id, reason = await _ensure_binding()
    if col_id is None:
        print(f"[skip] {reason}")
        return 0
    print(f"[bind] '{TARGET}' → {EMBED_MODEL} ({reason})")

    samples = _load_samples()
    if not samples:
        print(f"[skip] 샘플 문서 없음 ({SAMPLES_DIR})")
        return 0

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH, timeout=120) as c:
        # 파일명 단위 멱등(적대 리뷰 048): ready면 스킵, error면 삭제 후 재적재, 없으면 적재.
        # doc_count 게이트가 아니라 *실제 ready 파일명 집합*으로 완전성을 판단 → 부분 실패 자가치유.
        existing = (await c.get(f"/collections/{col_id}/documents")).json()
        by_name = {d["filename"]: d for d in existing}
        skipped = ingested = 0
        for fn, data in samples:
            prev = by_name.get(fn)
            if prev and prev.get("status") == "ready":
                skipped += 1
                print(f"[skip] {fn}: 이미 ready(멱등)")
                continue
            if prev:  # error/미완료 → 깨끗이 지우고 재적재(자가치유)
                await c.delete(f"/collections/{col_id}/documents/{prev['id']}")
                print(f"[reingest] {fn}: 이전 status={prev.get('status')} → 삭제 후 재적재")
            up = await c.post(
                f"/collections/{col_id}/documents",
                files={"file": (fn, data, "text/markdown")},
            )
            body = up.json()
            status = body.get("status")
            print(f"[ingest] {fn}: HTTP {up.status_code} status={status} chunks={body.get('chunk_count')}")
            if up.status_code != 201 or status != "ready":
                print(f"[error] 적재 실패: {body.get('error') or body}")
                return 1
            ingested += 1
        print(f"[summary] 적재 {ingested}개 · 스킵(멱등) {skipped}개 · 샘플 총 {len(samples)}개")

    # 검색 동작 확인 — 저장된 첫 청크 텍스트 질의 → 결정적 mock 벡터라 거리 0 → 1위 1.000.
    chunk0 = await _first_chunk_text(TARGET)
    col = await _collection_dict(TARGET)
    sink: list[dict] = []
    tool = runtime.build_rag_tool([col], sink)
    out = await tool.ainvoke({"query": chunk0, "top_k": 3})
    hits = sink[-1]["hits"] if sink else 0
    snippet = chunk0.strip().replace("\n", " ")[:24]
    ok = hits >= 1 and snippet in out
    print(f"[search] hits={hits} 1위-스니펫매칭={'OK' if snippet in out else 'MISS'}")

    async with SessionLocal() as s:
        cid = (await s.execute(select(Collection.id).where(Collection.name == TARGET))).scalar_one()
        n = await s.scalar(select(func.count()).select_from(Chunk).where(Chunk.collection_id == cid))
    print(f"[done] '{TARGET}' 적재 완료 — 문서 {len(samples)}개, 청크 {n}개, 검색 {'동작' if ok else '미동작'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
