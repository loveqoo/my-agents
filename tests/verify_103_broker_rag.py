"""스펙 103 검증 — 능력 브로커 RAG provider(kind=rag, 읽기전용).

핵심 불변식: provider 시임에 **셋째 kind(rag)** 를 붙여도 정책(allowlist∩RBAC·deny-by-default·존재
비노출·단일 `_permitted`)은 브로커 단일 지점에 남는다(스펙 100/101 무회귀). RAG는 읽기 전용 →
`approval_for` 항상 None(HIL 없음). invoke는 `search_collections` 코어 + `format_rag_hits` 공유
포맷(072 drift 0)을 재사용한다.

  [U] 단위(순수, DB 미접촉) — 네임스페이스 파싱·`_permitted` rag(1레벨 정확매치)·approval_for None·
      describe 스키마·col=None graceful·`_by_kind` 3종·시임 6메서드 계약·deny-by-default DB 미접촉.
  [H] 통합(실 mock 임베딩 + 실 DB) — seed 컬렉션 → discover/describe/invoke 왕복(untrusted,
      broker_invoke:rag 프레임) + 정책 격리(RBAC 거부/allow 밖 존재비노출) + 공유 포맷 drift 0.

전제: 072와 동일 — in-process 앱이 127.0.0.1:8000 mock 임베딩을 침 → dev 서버 필요.
실행: .venv/bin/python tests/verify_103_broker_rag.py
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from api import crypto, runtime  # noqa: E402
from api.auth import _token  # noqa: E402
from api.broker import (  # noqa: E402
    CapabilityNotFound,
    PolicyScopedBroker,
    RagProvider,
    _RagBacking,
    _kind_of,
    _parse_rag,
)
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Chunk, Collection, Document, ModelConfig  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
CP = "col_v103_"
MP = "mdl_v103_"
RAG_MAIN = f"rag:{CP}main"

DOC_TEXT = (
    "능력 브로커 RAG provider 검증 문서입니다. 이 문단은 충분히 길어 작은 청크 크기에서 여러 조각으로 "
    "분할됩니다. 각 조각은 임베딩되어 pgvector에 적재되고 cosine으로 검색됩니다.\n\n"
    "두 번째 문단입니다. 질의는 컬렉션 자신의 임베딩 모델로 임베딩해야 같은 벡터 공간이 됩니다.\n\n"
    "세 번째 문단입니다. 동일 텍스트 질의는 거리 0으로 정확히 1위가 되어 결정적 검증이 가능합니다."
) * 2


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _raise_factory():
    def make():
        raise AssertionError("거부/무해 경로가 DB를 만졌다(존재 누출 위험)")
    return make


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


_FAKE_COL = {"id": 1, "name": "x", "embed_base_url": "u", "embed_api_key": "k", "embed_model_id": "m"}


def unit_checks() -> None:
    print("[U] 단위(순수) — 네임스페이스·_permitted rag·approval_for·describe·_by_kind·시임 계약")
    # U1 네임스페이스 파싱(rag 접두사, 무회귀).
    check(_kind_of("rag:docs") == "rag", "U1 rag: 접두사 → kind rag")
    check(_kind_of("mcp:s/t") == "mcp" and _kind_of("agt_x") == "agent", "U1 mcp/agent 판정 무회귀")
    check(_parse_rag("rag:my docs") == "my docs", "U1 rag:name → name(공백 보존)")
    check(_parse_rag("rag:a:b/c") == "a:b/c", "U1 이름에 콜론/슬래시 있어도 접두사만 스트립")
    check(_parse_rag("agt_x") == "agt_x", "U1 접두사 없음 → 원본 방어")

    # U3 _permitted rag — 1레벨 정확 매치(mcp 서버-전체 특례 없음).
    bt = PolicyScopedBroker({RAG_MAIN}, lambda k: True, session_factory=_raise_factory())
    check(bt._permitted(RAG_MAIN) is True, "U3 정확 rag cap 허용 → permitted")
    check(bt._permitted(f"rag:{CP}other") is False, "U3 allow 밖 rag → deny(비노출)")
    brd = PolicyScopedBroker({RAG_MAIN}, lambda k: False, session_factory=_raise_factory())
    check(brd._permitted(RAG_MAIN) is False, "U3 RBAC 거부 → deny(교집합)")

    rp = RagProvider(_raise_factory())
    # U4 approval_for — RAG는 읽기전용 → 항상 None(HIL 없음).
    check(rp.approval_for(RAG_MAIN, {"text": "x"}) is None, "U4 rag approval_for → 항상 None(읽기전용)")

    # U5 describe input_schema — text 필수, top_k 선택.
    desc = rp.describe(_RagBacking(f"{CP}main", "설명", _FAKE_COL))
    props = (desc.input_schema or {}).get("properties", {})
    check(desc.kind == "rag" and desc.id == RAG_MAIN, "U5 describe id/kind")
    check("text" in props and desc.input_schema.get("required") == ["text"], "U5 text 필수 파라미터")
    check("top_k" in props, "U5 top_k 선택 파라미터 노출")

    # U6 _by_kind에 rag 포함(memory는 스펙 104서 추가 — ⊇로 완화, 무회귀).
    b = PolicyScopedBroker([], lambda k: True, session_factory=_raise_factory())
    check({"agent", "mcp", "rag"} <= set(b._by_kind), "U6 브로커가 agent·mcp·rag provider 보유")
    check(isinstance(b._by_kind["rag"], RagProvider), "U6 rag → RagProvider")

    # U7 셋째-provider 시임 무누수 측정 — 6메서드 계약 충족(agent/mcp와 동일 시그니처).
    for m in ("candidates", "load", "describe", "invoke", "node_label", "approval_for"):
        check(hasattr(rp, m), f"U7 RagProvider.{m} 존재(시임 계약)")
    check(rp.kind == "rag", "U7 RagProvider.kind == rag")
    check(rp.node_label(_RagBacking("docs", "", None)) == "broker_invoke:rag:docs", "U7 node_label 형식")


async def unit_async_checks() -> None:
    print("[U] 단위(async) — col=None graceful·deny-by-default DB 미접촉")
    rp = RagProvider(_raise_factory())
    # U8 col=None(임베딩 설정 불완전) → graceful 오류, DB/네트워크 미접촉.
    res = await rp.invoke(_RagBacking("docs", "", None), {"text": "q"})
    check(bool(res.error) and "불완전" in res.error and res.trust == "untrusted",
          "U8 col=None → graceful 오류(untrusted)")
    # candidates: rag 항목 없으면 [](DB 미접촉 — _raise_factory 안 터짐).
    check(await rp.candidates({"agt_x", "mcp:s/t"}) == [], "U8 rag 항목 없음 → [](DB 미접촉)")
    # 빈 리소스 이름 `rag:`는 능력 승격 안 함(적대 리뷰 103 P2) — candidates/load서 걸러 DB 미접촉.
    check(_parse_rag("rag:") == "", "U8 rag: → 빈 이름")
    check(await rp.candidates({"rag:"}) == [], "U8 빈 이름 `rag:` → [](승격 안 함, DB 미접촉)")
    check(await rp.load("rag:") is None, "U8 빈 이름 load → None(DB 미접촉)")
    # 빈 allowlist → discover [](provider.candidates 미호출).
    b_empty = PolicyScopedBroker([], lambda k: True, session_factory=_raise_factory())
    check(await b_empty.discover("문서") == [], "U8 빈 allowlist → [](DB 미접촉)")
    # rag allow 있으나 RBAC 거부 → provider 미호출(존재 누출 0).
    b_rbac = PolicyScopedBroker({RAG_MAIN}, lambda k: False, session_factory=_raise_factory())
    check(await b_rbac.discover("") == [], "U8 RBAC rag 거부 → [](존재 누출 0)")
    # allow 밖 invoke → not-found(_permitted가 load 이전에 거부 → DB 미접촉).
    b_main = PolicyScopedBroker({RAG_MAIN}, lambda k: True, session_factory=_raise_factory())
    r = await b_main.invoke(f"rag:{CP}other", {"text": "q"})
    check(r.error == "capability not found", "U8 allow 밖 rag invoke → not-found(존재 비노출)")


async def integration_checks() -> None:
    print("[H] 통합(실 mock 임베딩 + 실 DB) — discover/describe/invoke·정책격리·공유 포맷 drift 0")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH, timeout=60) as c:
        provs = (await c.get("/providers")).json()
        mock_p = next((p for p in provs if "_remote" in (p.get("base_url") or "")), None)
        check(mock_p is not None, "H seed: mock(_remote) provider 존재")
        mk = await c.post("/models", json={
            "name": f"{MP}embed", "provider_id": mock_p["id"], "model_id": "mock-embed",
            "kind": "embedding", "is_default": False, "params": {},
        })
        check(mk.status_code == 201, f"H seed: mock 임베딩 모델 201 (got {mk.status_code})")
        embed_mid = mk.json()["id"]
        for nm in ("main", "empty"):
            cc = await c.post("/collections", json={
                "name": f"{CP}{nm}", "embedding_model_id": embed_mid,
                "chunk_size": 200, "chunk_overlap": 20,
            })
            check(cc.status_code == 201, f"H seed: 컬렉션 {nm} 201 (got {cc.status_code})")
        cid = next(x["id"] for x in (await c.get("/collections")).json() if x["name"] == f"{CP}main")
        up = await c.post(f"/collections/{cid}/documents",
                          files={"file": ("main.txt", DOC_TEXT.encode("utf-8"), "text/plain")})
        check(up.json()["status"] == "ready", "H seed: main 인제스트 ready")
        chunk0 = await _first_chunk_text(f"{CP}main")

        # 브로커: allow=rag:main, RBAC 허용, 실 DB.
        b = PolicyScopedBroker({RAG_MAIN}, lambda k: True, session_factory=SessionLocal)

        # H1 discover → rag cap 노출.
        caps = await b.discover(CP)  # 부분일치(컬렉션 이름 접두사)
        rag_caps = [x for x in caps if x.kind == "rag"]
        check(any(x.id == RAG_MAIN for x in rag_caps), f"H1 discover → rag cap 노출 (got {[x.id for x in caps]})")

        # H2 describe → input_schema.
        d = await b.describe(RAG_MAIN)
        check(d.kind == "rag" and "text" in (d.input_schema or {}).get("properties", {}),
              "H2 describe → kind=rag·text 파라미터")

        # H3 invoke → 검색 결과 텍스트(untrusted) + 관측 프레임 1개.
        res = await b.invoke(RAG_MAIN, {"text": chunk0})
        check(res.error is None and "문서 검색 결과" in res.text, f"H3 invoke → 검색 결과 텍스트 (err={res.error})")
        check(res.trust == "untrusted", "H3 결과 trust=untrusted(데이터 채널 격리 대상)")
        frames = [i for i in b.invocations if i["node"] == f"broker_invoke:rag:{CP}main"]
        check(len(frames) == 1, f"H3 broker.invocations에 rag 프레임 1개 (got {len(frames)})")
        secret = (await _collection_dict(f"{CP}main"))["embed_api_key"]
        check(bool(secret) and secret not in res.text, "H3 복호화 api_key 결과 미노출")

        # H4 정책 격리: RBAC rag 거부 → discover에 rag 0(DB 미접촉).
        b_deny = PolicyScopedBroker({RAG_MAIN}, lambda k: False, session_factory=_raise_factory())
        check(await b_deny.discover(CP) == [], "H4 RBAC rag 거부 → discover [](DB 미접촉)")

        # H5 allow 밖(rag:empty는 실존하나 미허가) invoke → not-found(존재 비노출).
        r5 = await b.invoke(f"rag:{CP}empty", {"text": "x"})
        check(r5.error == "capability not found", "H5 allow 밖(실존) invoke → not-found(존재 비노출)")
        # H6 allow 밖 describe → CapabilityNotFound(미존재·미허가 동일).
        try:
            await b.describe(f"rag:{CP}empty")
            check(False, "H6 allow 밖 describe CapabilityNotFound 기대했으나 통과")
        except CapabilityNotFound:
            check(True, "H6 allow 밖 describe → CapabilityNotFound(존재 비노출)")

        # H7 공유 포맷 drift 0 — provider invoke text == format_rag_hits(search_collections(...)).
        col = await _collection_dict(f"{CP}main")
        core_hits = await runtime.search_collections([col], chunk0, 4)
        check(res.text == runtime.format_rag_hits(core_hits), "H7 provider invoke == 공유 코어+포맷(drift 0)")

        # H8 빈 컬렉션 위임(허가) → graceful 무결과 텍스트(코어 [] → 공유 포맷).
        b_empty_allow = PolicyScopedBroker({f"rag:{CP}empty"}, lambda k: True, session_factory=SessionLocal)
        r8 = await b_empty_allow.invoke(f"rag:{CP}empty", {"text": "아무거나 질의"})
        check(r8.error is None and "찾지 못했습니다" in r8.text, "H8 빈 컬렉션 → graceful 무결과 텍스트")

        # H9 과대 질의(적대 리뷰 103 P2) — 4000자 초과도 코어서 잘려 크래시/오류 없이 처리.
        r9 = await b.invoke(RAG_MAIN, {"text": "가" * 6000})
        check(r9.error is None and "문서 검색 결과" in r9.text, "H9 6000자 질의 → 상한 처리(크래시 없음)")


async def main() -> None:
    await _cleanup()
    try:
        unit_checks()
        await unit_async_checks()
        await integration_checks()
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
