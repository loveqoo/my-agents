"""영화 엔티티 데모 적재 — 임베딩 모델 선택형(스펙 311). `ingest_rag_samples.py` 계보.

왜: 엔티티 RAG(스펙 149)의 첫 구동 예제가 없다. 이 로더가 `movies.jsonl`(행=1영화, metadata에 숫자
id 여럿·data=줄거리)을 **고른 임베딩 모델**에 바인딩된 `kind='entity'` 컬렉션에 적재한다.
- `--model mock-embed` → 1024차원·결정적 → 스펙 310 평가 판정 픽스처(의미는 아님).
- `--model <실모델>` → 진짜 의미 검색 데모("우주 고립"→인터스텔라).

동작:
  1. (게이트) 임베딩 모델이 하나도 없으면 스킵. --model 지정 시 그 이름, 없으면 기본 임베딩 모델.
  2. `kind='entity'` 컬렉션(기본 `movies-demo`, 스펙148 대시)을 선택 모델에 바인딩 생성(있으면 재사용).
  3. `movies.jsonl`을 실 인제스트 엔드포인트로 적재(parse→embed→pgvector). 파일 단위 멱등.
  4. 검색 1회로 동작 + **hit의 meta에 movie_id 등 id가 실려 나오는지** 확인(스펙 310 전제).

전제: 마이그레이션 DB + 라이브 서버(선택 모델의 임베딩 엔드포인트 도달; mock은 앱 내
`/_remote/v1/embeddings`, 실모델은 그 원격).
실행: cd packages/api && uv run python scripts/ingest_movie_entities.py [--model NAME] [--collection NAME]
"""

import argparse
import asyncio
import json
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
from api.models import Chunk, Collection, ModelConfig  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "entity_samples", "movies.jsonl"
)
DESC = "영화 데모 엔티티 컬렉션 — 엔티티 RAG 검색·평가 예제(스펙 311)."


async def _resolve_model(name: str | None) -> tuple[str, str] | None:
    """임베딩 모델 해석. name 지정 시 그 이름, 아니면 기본(is_default)→첫 임베딩. 없으면 None(게이트)."""
    async with SessionLocal() as s:
        q = select(ModelConfig).where(ModelConfig.kind == "embedding")
        if name:
            q = q.where(ModelConfig.name == name)
        rows = (await s.execute(q)).scalars().all()
        if not rows:
            return None
        chosen = rows[0] if name else next((m for m in rows if getattr(m, "is_default", False)), rows[0])
        return str(chosen.id), chosen.name


async def _find_collection(name: str) -> Collection | None:
    async with SessionLocal() as s:
        return (
            await s.execute(select(Collection).where(Collection.name == name))
        ).scalar_one_or_none()


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


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="임베딩 모델 이름(기본: 기본 임베딩 모델)")
    ap.add_argument("--collection", default="movies-demo", help="컬렉션 이름(기본: movies-demo)")
    args = ap.parse_args()
    coll = args.collection

    resolved = await _resolve_model(args.model)
    if resolved is None:
        print(f"[skip] 임베딩 모델 없음({args.model or '기본'}) — 게이트로 적재 스킵")
        return 0
    model_id, model_name = resolved
    print(f"[model] '{coll}' → 임베딩 모델 '{model_name}'")

    with open(DATA_FILE, "rb") as f:
        data = f.read()
    n_rows = sum(1 for ln in data.splitlines() if ln.strip())

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH, timeout=120) as c:
        # 컬렉션 확보(없으면 kind='entity'로 생성, 있으면 재사용 — 생성 후 모델 불변 스펙149).
        existing = await _find_collection(coll)
        if existing is None:
            r = await c.post(
                "/collections",
                json={"name": coll, "description": DESC, "kind": "entity", "embedding_model_id": model_id},
            )
            if r.status_code not in (200, 201):
                print(f"[error] 컬렉션 생성 실패 HTTP {r.status_code}: {r.text[:300]}")
                return 1
            col_id = r.json()["id"]
            print(f"[create] '{coll}' 생성(kind=entity)")
        else:
            if existing.kind != "entity":
                print(f"[error] '{coll}'이 이미 kind={existing.kind}로 존재 — 엔티티 데모엔 다른 이름을 쓰세요")
                return 1
            col_id = str(existing.id)
            if str(existing.embedding_model_id) != model_id:
                print(f"[warn] '{coll}'은 이미 다른 임베딩 모델에 바인딩됨(불변) — 기존 모델로 적재 진행")
            print(f"[reuse] '{coll}' 재사용")

        # 파일 단위 멱등(ingest_rag_samples 계보): ready면 스킵, error면 삭제 후 재적재.
        resp = (await c.get(f"/collections/{col_id}/documents", params={"limit": 100})).json()
        items = resp.get("items", []) if isinstance(resp, dict) else resp
        prev = next((d for d in items if d["filename"] == "movies.jsonl"), None)
        if prev and prev.get("status") == "ready":
            print("[skip] movies.jsonl 이미 ready(멱등)")
        else:
            if prev:
                await c.delete(f"/collections/{col_id}/documents/{prev['id']}")
                print(f"[reingest] movies.jsonl: 이전 status={prev.get('status')} → 삭제 후 재적재")
            up = await c.post(
                f"/collections/{col_id}/documents",
                files={"file": ("movies.jsonl", data, "application/x-ndjson")},
            )
            body = up.json()
            print(f"[ingest] movies.jsonl: HTTP {up.status_code} status={body.get('status')} chunks={body.get('chunk_count')}")
            if up.status_code != 201 or body.get("status") != "ready":
                print(f"[error] 적재 실패: {body.get('error') or body}")
                return 1

    # 검색 확인 — 첫 영화의 data로 질의(mock=결정적 거리0로 그 엔티티 상위). hit의 meta에 id 실림 단언.
    first = json.loads(data.splitlines()[0])
    query = first["data"] if isinstance(first["data"], str) else json.dumps(first["data"], ensure_ascii=False)
    col_dict = await _collection_dict(coll)
    hits = await runtime.search_collections([col_dict], query, top_k=3)
    has_meta = bool(hits) and isinstance(hits[0].get("meta"), dict) and hits[0]["meta"].get("movie_id") is not None
    print(f"[search] hits={len(hits)} · 1위 meta={hits[0].get('meta') if hits else None}")

    async with SessionLocal() as s:
        cid = (await s.execute(select(Collection.id).where(Collection.name == coll))).scalar_one()
        nchunk = await s.scalar(select(func.count()).select_from(Chunk).where(Chunk.collection_id == cid))
    ok = has_meta and nchunk == n_rows
    print(f"[done] '{coll}' — 행 {n_rows} · 청크 {nchunk} · meta노출 {'OK' if has_meta else 'MISS'} → {'성공' if ok else '실패'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
