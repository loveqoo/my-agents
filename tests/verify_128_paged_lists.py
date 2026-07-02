"""verify_128 — 문서 페이지 목록 API + 공용 셸 일반화 백엔드 (스펙 128).

인프로세스 httpx(ASGI) + 실 DB(verify_034 패턴). 검증용 컬렉션 1개 + 문서 26건을 고유 prefix로
삽입 → 단언 → 컬렉션 삭제(문서 CASCADE, 자가정리).

단언:
  D1 셰이프 {items,total} · total=26.
  D2 1페이지 20건, 2페이지 6건, 페이지 간 중복 없음(같은 created_at에서도 id tiebreak 결정성).
  D3 q 부분일치: 'doc-7' → 1건.
  D4 ILIKE 이스케이프: 'a%b_c' 리터럴만 1건, '%' 단독 → 특수문자 행만 1건(전체 매치로 안 샘).
  D5 limit>100 → 422, offset 음수 → 422 (경계 스키마).
  D6 미존재 컬렉션 → 404.
세션 무회귀는 기존 verify_034(페이징)·verify_098(검색)을 별도 실행으로 확인.

실행: uv run --project packages/api python tests/verify_128_paged_lists.py
"""

import asyncio
import os
import sys
import uuid as _uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.auth import _token  # noqa: E402
from api.db import SessionLocal as async_session  # noqa: E402
from api.main import app  # noqa: E402
from api.models import RAG_EMBED_DIMS, Collection, Document, ModelConfig  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
passed = 0
TAG = f"v128-{_uuid.uuid4().hex[:6]}"


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def _seed() -> str:
    async with async_session() as sess:
        emb = (
            await sess.execute(select(ModelConfig).where(ModelConfig.kind == "embedding").limit(1))
        ).scalar_one_or_none()
        if emb is None:
            raise RuntimeError("검증 불가: embedding 모델이 시드돼 있지 않음")
        col = Collection(
            name=f"{TAG}-col",
            description="verify_128",
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            chunk_size=1000,
            chunk_overlap=200,
            status="empty",
        )
        sess.add(col)
        await sess.flush()
        for i in range(1, 26):
            sess.add(Document(collection_id=col.id, filename=f"{TAG}-doc-{i}.txt", byte_size=1, chunk_count=0, status="ready"))
        # ILIKE 이스케이프 검증용 특수문자 파일명.
        sess.add(Document(collection_id=col.id, filename=f"{TAG}-a%b_c.txt", byte_size=1, chunk_count=0, status="ready"))
        await sess.commit()
        return str(col.id)


async def _cleanup(cid: str) -> None:
    async with async_session() as sess:
        col = await sess.get(Collection, _uuid.UUID(cid))
        if col is not None:
            await sess.delete(col)  # documents CASCADE
            await sess.commit()
    print("  (정리: 컬렉션+문서 CASCADE 삭제)")


async def main() -> None:
    cid = await _seed()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH) as c:
            base = f"/collections/{cid}/documents"

            r1 = await c.get(base, params={"limit": 20, "offset": 0})
            d1 = r1.json()
            check(r1.status_code == 200 and set(d1) >= {"items", "total"} and d1["total"] == 26,
                  f"D1 셰이프+total=26 (got {r1.status_code}, total={d1.get('total')})")
            check(len(d1["items"]) == 20, f"D2a 1페이지 20건 (got {len(d1['items'])})")

            r2 = await c.get(base, params={"limit": 20, "offset": 20})
            d2 = r2.json()
            check(len(d2["items"]) == 6, f"D2b 2페이지 6건 (got {len(d2['items'])})")
            ids1 = {it["id"] for it in d1["items"]}
            check(not ids1 & {it["id"] for it in d2["items"]},
                  "D2c 페이지 간 중복 없음(동일 created_at서 id tiebreak 결정성)")

            r3 = await c.get(base, params={"q": "doc-7", "limit": 20, "offset": 0})
            check(r3.json()["total"] == 1, f"D3 부분일치 'doc-7' → 1건 (got {r3.json()['total']})")

            r4 = await c.get(base, params={"q": "a%b_c", "limit": 20, "offset": 0})
            check(r4.json()["total"] == 1 and "a%b_c" in r4.json()["items"][0]["filename"],
                  f"D4a 와일드카드 리터럴 매치 (got {r4.json()['total']})")
            r5 = await c.get(base, params={"q": "%", "limit": 20, "offset": 0})
            check(r5.json()["total"] == 1, f"D4b '%' 단독 → 특수문자 행만 (got {r5.json()['total']})")

            r6 = await c.get(base, params={"limit": 999, "offset": 0})
            check(r6.status_code == 422, f"D5a limit>100 → 422 (got {r6.status_code})")
            r7 = await c.get(base, params={"limit": 20, "offset": -1})
            check(r7.status_code == 422, f"D5b offset<0 → 422 (got {r7.status_code})")

            r8 = await c.get(f"/collections/{_uuid.uuid4()}/documents", params={"limit": 20, "offset": 0})
            check(r8.status_code == 404, f"D6 미존재 컬렉션 → 404 (got {r8.status_code})")
    finally:
        await _cleanup(cid)

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
