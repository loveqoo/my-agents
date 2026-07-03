"""verify_163 — RAG 컬렉션 사용 공개(publish) 토글(스펙 163).

컬렉션은 소유자만 쓸 수 있던 걸(agent_may_wire, 스펙 113) MCP처럼 publish로 타 작성자 에이전트에도
개방. 수정·삭제는 여전히 소유자(may_manage). owner_id(관리)와 published(사용)는 직교.

  U1~U4 agent_may_wire 단위 — published가 타 작성자 배선을 뒤집는 핵심 게이트(chat.py:305와 동일 술어).
  H1 alice publish=true → 200·published=true·can_manage=true.
  H2 bob publish 시도 → 404-fold(may_manage 아님, 존재 비노출).
  H3 published는 can_manage와 직교 — publish 후에도 bob can_manage=false.
  H4 alice unpublish → published=false 멱등.
실행: cd packages/api && uv run python ../../tests/verify_163_collection_publish.py
"""
import asyncio
import uuid

import httpx

from api.auth import current_principal
from api.db import SessionLocal
from api.main import app
from api.models import Collection, ModelConfig, Provider
from api.ownership import agent_may_wire

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

    alice, bob, admin = Stub(), Stub(), Stub(is_superuser=True)
    aid = str(alice.id)
    bid = str(bob.id)

    # ---- U: agent_may_wire 단위(chat.py:305와 동일 술어). owner_privileged=False, RBAC 미부여 가정. ----
    # 비공개 컬렉션(owner=alice)을 bob 에이전트가 배선 → 차단.
    check(agent_may_wire(aid, False, bid, "rag", "c", owner_privileged=False) is False,
          "U1 비공개 alice 컬렉션 → bob 에이전트 배선 차단")
    # 공개하면 → bob 에이전트도 배선 허용(rule 4).
    check(agent_may_wire(aid, True, bid, "rag", "c", owner_privileged=False) is True,
          "U2 공개 alice 컬렉션 → bob 에이전트 배선 허용")
    # 자기 소유는 공개 여부와 무관하게 허용(rule 3).
    check(agent_may_wire(aid, False, aid, "rag", "c", owner_privileged=False) is True,
          "U3 비공개라도 자기 소유는 배선 허용")
    # 공개해도 관리(may_manage)와 무관 — 여기선 배선(사용) 술어만. (관리 직교는 H3에서.)
    check(agent_may_wire(aid, True, None, "rag", "c", owner_privileged=False) is True,
          "U4 신뢰 저작 맥락(agent_owner None)은 항상 배선")

    # ---- 컬렉션 생성(직접 삽입 — HTTP create는 probe 필요). alice 소유. ----
    cid = None
    prov_id = model_id = None
    async with SessionLocal() as s:
        prov = Provider(name=f"prov-{uuid.uuid4().hex[:8]}", base_url="http://x", kind="remote")
        s.add(prov)
        await s.flush()
        prov_id = prov.id
        em = ModelConfig(name=f"emb-{uuid.uuid4().hex[:8]}", provider_id=prov.id,
                         model_id="emb", kind="embedding")
        s.add(em)
        await s.flush()
        model_id = em.id
        col = Collection(name=f"col-{uuid.uuid4().hex[:8]}", embedding_model_id=em.id,
                         dims=8, owner_id=aid, published=False)
        s.add(col)
        await s.flush()
        cid = col.id
        await s.commit()

    t = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=t, base_url="http://t", timeout=60) as c:
            # H1 alice publish=true.
            _as(alice)
            r = await c.put(f"/collections/{cid}/publish", json={"published": True})
            check(r.status_code == 200, f"H1 alice publish 200 (got {r.status_code})")
            j = r.json()
            check(j.get("published") is True, "H1 published=true 반영")
            check(j.get("can_manage") is True, "H1 소유자 can_manage=true")

            # H2 bob publish 시도 → 404-fold.
            _as(bob)
            r = await c.put(f"/collections/{cid}/publish", json={"published": False})
            check(r.status_code == 404, f"H2 bob publish 404-fold (got {r.status_code})")

            # H3 published ⟂ can_manage — bob 목록서 published=true지만 can_manage=false.
            _as(bob)
            lst = (await c.get("/collections")).json()
            row = next((x for x in lst if x["id"] == str(cid)), None)
            check(row is not None, "H3 bob도 컬렉션 목록서 봄(가시성은 전역)")
            check(row and row["published"] is True, "H3 bob 시야: published=true(사용 공개됨)")
            check(row and row["can_manage"] is False, "H3 bob 시야: can_manage=false(관리 직교)")

            # H4 alice unpublish 멱등.
            _as(alice)
            r = await c.put(f"/collections/{cid}/publish", json={"published": False})
            check(r.status_code == 200 and r.json().get("published") is False, "H4 alice unpublish → false")

            # ---- H5~H7 직접 엔드포인트 사용 게이트(codex 163 High/Med) — 배선 우회 봉인 ----
            # 지금 published=false. bob이 직접 search → 404-fold(비공개 타인 컬렉션 청크 유출 차단).
            _as(bob)
            r = await c.post(f"/collections/{cid}/search", json={"query": "hi", "top_k": 3})
            check(r.status_code == 404, f"H5 bob search 비공개 → 404-fold (got {r.status_code})")
            # bob이 직접 문서목록 → 404-fold(파일명·메타 유출 차단).
            r = await c.get(f"/collections/{cid}/documents")
            check(r.status_code == 404, f"H6 bob documents 비공개 → 404-fold (got {r.status_code})")
            # 소유자 alice는 비공개라도 자기 것 사용 가능(문서목록 200 — 임베딩 설정 무관 경로).
            _as(alice)
            r = await c.get(f"/collections/{cid}/documents")
            check(r.status_code == 200, f"H7 alice(소유자) 자기 문서목록 200 (got {r.status_code})")
            # publish 후엔 bob도 문서목록 접근 가능(사용 공개).
            await c.put(f"/collections/{cid}/publish", json={"published": True})
            _as(bob)
            r = await c.get(f"/collections/{cid}/documents")
            check(r.status_code == 200, f"H7 publish 후 bob 문서목록 200(사용 공개) (got {r.status_code})")
    finally:
        app.dependency_overrides.pop(current_principal, None)
        # 정리
        async with SessionLocal() as s:
            if cid:
                obj = await s.get(Collection, cid)
                if obj:
                    await s.delete(obj)
            await s.commit()
        async with SessionLocal() as s:
            if model_id:
                m = await s.get(ModelConfig, model_id)
                if m:
                    await s.delete(m)
            await s.commit()
        async with SessionLocal() as s:
            if prov_id:
                p = await s.get(Provider, prov_id)
                if p:
                    await s.delete(p)
            await s.commit()

    print("\nPASS — 0 failed" if not _fails else f"\nFAIL — {len(_fails)} failed")
    raise SystemExit(1 if _fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
