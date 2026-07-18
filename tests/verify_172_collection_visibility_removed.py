"""verify_172 — RAG 컬렉션 공개/비공개 제거 후 접근 모델(스펙 172, 163 대체).

스펙 163의 published(사용 공개) 축을 걷어내고 "사용=전부 공용"으로 단순화. 검증할 새 불변식:
  H1 bob(비소유자)이 alice 컬렉션 문서목록 → **200**(사용 개방; 163에선 404-fold였음).
  H2 bob search → **비-404·비-403**(사용 게이트 통과; 임베딩 스텁이라 502 가능, 게이트는 뚫림).
  H3 bob update(PUT) → **404-fold**(관리는 여전히 소유자만, assert_may_manage).
  H4 bob delete → **404-fold**(관리 소유자만).
  H5 익명(인증 없음) 문서목록 → **401**(current_principal이 막음 — 로그인한 누구나지 익명은 아님).
  H6 publish 엔드포인트 제거 확인 → PUT /{cid}/publish → **404**(라우트 없음).
  H7 alice(소유자) 자기 문서목록 → **200**(무회귀).
실행: cd packages/api && uv run python ../../tests/verify_172_collection_visibility_removed.py
"""

import asyncio
import uuid

import httpx

from api.auth import current_principal
from api.db import SessionLocal
from api.main import app
from api.models import Collection, ModelConfig, Provider

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Stub:
    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.is_active = True
        self.is_verified = True
        self.email = f"u-{self.id.hex[:6]}@x"


def _as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


async def main() -> None:
    from api import authz

    await authz.init_authz()

    alice, bob = Stub(), Stub()
    aid = str(alice.id)

    cid = prov_id = model_id = None
    async with SessionLocal() as s:
        prov = Provider(name=f"prov-{uuid.uuid4().hex[:8]}", base_url="http://x", kind="remote")
        s.add(prov)
        await s.flush()
        prov_id = prov.id
        em = ModelConfig(
            name=f"emb-{uuid.uuid4().hex[:8]}",
            provider_id=prov.id,
            model_id="emb",
            kind="embedding",
        )
        s.add(em)
        await s.flush()
        model_id = em.id
        # published 컬럼은 스펙 172에서 제거됨 — 생성 인자에 넣지 않는다(넣으면 TypeError).
        col = Collection(
            name=f"col-{uuid.uuid4().hex[:8]}", embedding_model_id=em.id, dims=8, owner_id=aid
        )
        s.add(col)
        await s.flush()
        cid = col.id
        await s.commit()

    t = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=t, base_url="http://t", timeout=60) as c:
            # H1 bob(비소유자) 문서목록 → 200(사용 개방).
            _as(bob)
            r = await c.get(f"/collections/{cid}/documents")
            check(
                r.status_code == 200,
                f"H1 bob 비소유자 문서목록 200(사용 개방) (got {r.status_code})",
            )

            # H2 bob search → 게이트 통과(비-404·비-403). 임베딩 스텁이라 200/502 어느 쪽이든 게이트는 뚫림.
            r = await c.post(f"/collections/{cid}/search", json={"query": "hi", "top_k": 3})
            check(
                r.status_code not in (403, 404),
                f"H2 bob search 사용 게이트 통과(비-404/403) (got {r.status_code})",
            )

            # H3 bob update(PUT) → 404-fold(관리 소유자만).
            r = await c.put(f"/collections/{cid}", json={"description": "hijack"})
            check(
                r.status_code == 404, f"H3 bob update 404-fold(관리 소유자만) (got {r.status_code})"
            )

            # H4 bob delete → 404-fold(관리 소유자만).
            r = await c.delete(f"/collections/{cid}")
            check(
                r.status_code == 404, f"H4 bob delete 404-fold(관리 소유자만) (got {r.status_code})"
            )

            # H5 익명(오버라이드 제거 → 진짜 current_principal) → 401.
            app.dependency_overrides.pop(current_principal, None)
            r = await c.get(f"/collections/{cid}/documents")
            check(r.status_code == 401, f"H5 익명 문서목록 401(로그인 필요) (got {r.status_code})")

            # H6 publish 엔드포인트 제거 확인 → 404(라우트 없음).
            _as(alice)
            r = await c.put(f"/collections/{cid}/publish", json={"published": True})
            check(r.status_code == 404, f"H6 publish 엔드포인트 제거됨 → 404 (got {r.status_code})")

            # H7 alice(소유자) 문서목록 → 200(무회귀).
            r = await c.get(f"/collections/{cid}/documents")
            check(
                r.status_code == 200, f"H7 alice 소유자 문서목록 200(무회귀) (got {r.status_code})"
            )
    finally:
        app.dependency_overrides.pop(current_principal, None)
        for pk, model in ((cid, Collection), (model_id, ModelConfig), (prov_id, Provider)):
            if pk:
                async with SessionLocal() as s:
                    obj = await s.get(model, pk)
                    if obj:
                        await s.delete(obj)
                    await s.commit()

    print("\nPASS — 0 failed" if not _fails else f"\nFAIL — {len(_fails)} failed")
    raise SystemExit(1 if _fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
