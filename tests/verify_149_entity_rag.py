"""verify_149 — 엔티티 RAG (스펙 149).

  V1 순수 함수: entity_text 직렬화 · parse_entity_lines(정상/위반 행 번호/캡/스키마/빈 파일).
  V2 컬렉션: kind=entity 생성 + entity_schema(무효 스키마 400 · 문서형에 스키마 400).
  V3 업로드: 위반 JSONL=400(문서 행 미생성) · 정상 JSONL=1행 1청크+meta 저장.
  V4 검색: 엔티티 hit에 meta 동반 · 문서형 hit은 meta=None(무회귀).
  V5 인-챗 도구 포맷: metadata 표기 포함.
실행: uv run --project packages/api --env-file .env python tests/verify_149_entity_rag.py
※ mock-embed 임베딩이 자기 서비스(127.0.0.1:8000)를 호출하므로 API 서버가 떠 있어야 한다.
"""
import asyncio
import io
import json
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from fastapi import HTTPException, UploadFile  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import rag as RG  # noqa: E402
from api import rag_ingest as RI  # noqa: E402
from api import runtime as RT  # noqa: E402
from api.models import Chunk, Collection, Document, ModelConfig  # noqa: E402
from api.schemas import CollectionIn, CollectionUpdate  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def expect_400(coro_msg):
    def deco(msg):
        return msg
    return deco


class _P:
    def __init__(self):
        self.id = _uuid.uuid4()
        self.is_superuser = True


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


async def main():
    from api.authz import init_authz
    await init_authz()
    admin = _P()
    tag = f"v149-{_uuid.uuid4().hex[:6]}"

    # ---- V1 순수 함수 ----
    check(RI.entity_text("텍스트 그대로") == "텍스트 그대로", "V1a data=문자열 그대로")
    t = RI.entity_text({"title": "상품A", "tags": ["x", "y"]})
    check("title: 상품A" in t and 'tags: ["x", "y"]' in t, f"V1b data=객체 평탄화(중첩 JSON): {t!r}")
    good = b'\n'.join([
        json.dumps({"metadata": {"pid": i, "sid": i * 10}, "data": {"name": f"상품{i}", "desc": f"설명 {i}"}},
                    ensure_ascii=False).encode() for i in range(3)
    ]) + b"\n\n"  # 후행 빈 줄 허용
    rows = RI.parse_entity_lines(good)
    check(len(rows) == 3 and rows[0][1] == {"pid": 0, "sid": 0}, "V1c 정상 3행 파싱 + meta 보존")
    for bad, why in [
        (b'{"metadata": {}, "data": {"a": 1}}\nnot-json', "2번째 줄 JSON 파싱"),
        (b'[1,2]', "객체 아님"),
        (b'{"metadata": "x", "data": "y"}', "metadata 비객체"),
        (b'{"metadata": {}, "data": 42}', "data 타입"),
        (b'{"metadata": {}, "data": "   "}', "빈 텍스트"),
        (b'', "빈 파일"),
        ("한글아닌바이트".encode("euc-kr"), "비UTF-8"),
    ]:
        try:
            RI.parse_entity_lines(bad)
            check(False, f"V1d 거부돼야: {why}")
        except RI.EntityParseError as e:
            check(True, f"V1d 거부({why}): {str(e)[:40]}")
    try:
        RI.parse_entity_lines(b'{"metadata": {}, "data": "%s"}' % (b"x" * 9000))
        check(False, "V1e 행 텍스트 캡 초과 거부돼야")
    except RI.EntityParseError:
        check(True, "V1e 행 텍스트 캡(8000자) 거부")
    # 행 번호 포함 확인
    try:
        RI.parse_entity_lines(b'{"metadata": {}, "data": "ok row"}\n{"metadata": 1, "data": "x"}')
    except RI.EntityParseError as e:
        check("2번째 줄" in str(e), f"V1f 위반 행 번호 명시: {str(e)[:40]}")
    # 스키마 검증
    schema = {"type": "object", "properties": {"metadata": {"type": "object", "required": ["pid"]}},
              "required": ["metadata", "data"]}
    ok_line = json.dumps({"metadata": {"pid": 1}, "data": "텍스트다섯자이상"}).encode()
    bad_line = json.dumps({"metadata": {"sid": 1}, "data": "텍스트다섯자이상"}).encode()
    check(len(RI.parse_entity_lines(ok_line, schema=schema)) == 1, "V1g 스키마 통과")
    try:
        RI.parse_entity_lines(bad_line, schema=schema)
        check(False, "V1h 스키마 위반 거부돼야")
    except RI.EntityParseError as e:
        check("스키마 위반" in str(e), f"V1h 스키마 위반 거부: {str(e)[:50]}")
    # metadata 직렬화 캡(codex 149 Medium)
    big_meta = json.dumps({"metadata": {"blob": "x" * 3000}, "data": "텍스트다섯자이상"}).encode()
    try:
        RI.parse_entity_lines(big_meta)
        check(False, "V1i metadata 캡 초과 거부돼야")
    except RI.EntityParseError as e:
        check("metadata" in str(e), f"V1i metadata 캡(2000자) 거부: {str(e)[:40]}")

    # ---- V2 컬렉션 생성 ----
    async with async_session() as s:
        emb = (await s.execute(select(ModelConfig).where(ModelConfig.name == "mock-embed"))).scalar_one()
        emb_id = emb.id
    async with async_session() as s:
        try:
            await RG.create_collection(
                CollectionIn(name=f"{tag}-bad", kind="entity", entity_schema={"type": "nope"},
                             embedding_model_id=emb_id), session=s, principal=admin)
            check(False, "V2a 무효 스키마 400이어야")
        except HTTPException as e:
            check(e.status_code == 400 and "Schema" in str(e.detail), f"V2a 무효 스키마 400 (got {e.status_code})")
    async with async_session() as s:
        try:
            await RG.create_collection(
                CollectionIn(name=f"{tag}-doc-schema", kind="document", entity_schema=schema,
                             embedding_model_id=emb_id), session=s, principal=admin)
            check(False, "V2b 문서형+스키마 400이어야")
        except HTTPException as e:
            check(e.status_code == 400, f"V2b 문서형+스키마 400 (got {e.status_code})")
    async with async_session() as s:
        try:
            await RG.create_collection(
                CollectionIn(name=f"{tag}-redos", kind="entity",
                             entity_schema={"type": "object",
                                            "properties": {"data": {"type": "string", "pattern": "^(a+)+$"}}},
                             embedding_model_id=emb_id), session=s, principal=admin)
            check(False, "V2e 정규식 키워드 스키마 400이어야(ReDoS 경계)")
        except HTTPException as e:
            check(e.status_code == 400 and "pattern" in str(e.detail), f"V2e 정규식 키워드 400 (got {e.status_code})")
    async with async_session() as s:
        col = await RG.create_collection(
            CollectionIn(name=f"{tag}-entities", description="검증 엔티티", kind="entity", entity_schema=schema,
                         embedding_model_id=emb_id), session=s, principal=admin)
        col_id = col.id
        check(col.kind == "entity" and col.entity_schema == schema, "V2c 엔티티 컬렉션 생성(kind+스키마 저장)")
    async with async_session() as s:
        # 명시적 null=스키마 제거 → 재등록(codex 149 — 오등록 스키마 해제 경로)
        out = await RG.update_collection(col_id, CollectionUpdate(entity_schema=None), session=s, principal=admin)
        check(out.entity_schema is None, "V2f 명시적 null로 스키마 제거")
    async with async_session() as s:
        out = await RG.update_collection(col_id, CollectionUpdate(entity_schema=schema), session=s, principal=admin)
        check(out.entity_schema == schema, "V2g 스키마 재등록")
    async with async_session() as s:
        doc_cols = (await s.execute(select(Collection).where(Collection.kind == "document"))).scalars().all()
        target_doc = next((c for c in doc_cols if c.name == "docs-kb"), None)
        try:
            await RG.update_collection(_uuid.UUID(str(target_doc.id)) if target_doc else col_id,
                                       CollectionUpdate(entity_schema=schema), session=s, principal=admin)
            check(target_doc is None, "V2d 문서형 스키마 갱신 400이어야(문서형 존재 시)")
        except HTTPException as e:
            check(e.status_code == 400, f"V2d 문서형 스키마 갱신 400 (got {e.status_code})")

    try:
        # ---- V3 업로드 ----
        async with async_session() as s:
            try:
                await RG.ingest_document(col_id, file=_upload("bad.jsonl", bad_line),
                                         session=s, principal=admin)
                check(False, "V3a 스키마 위반 업로드 400이어야")
            except HTTPException as e:
                check(e.status_code == 400 and "1번째 줄" in str(e.detail),
                      f"V3a 위반 업로드 400+행 번호 (got {e.status_code}: {str(e.detail)[:40]})")
        async with async_session() as s:
            n_docs = (await s.execute(select(Document).where(Document.collection_id == col_id))).scalars().all()
            check(len(n_docs) == 0, "V3b 거부 업로드는 문서 행을 남기지 않음(fail-closed)")
        ent_file = b"\n".join([
            json.dumps({"metadata": {"pid": i, "order_id": f"o-{i}"},
                        "data": {"name": f"무선 키보드 {i}", "desc": "저소음 무선 키보드입니다"}},
                       ensure_ascii=False).encode() for i in range(1, 4)
        ])
        async with async_session() as s:
            doc = await RG.ingest_document(col_id, file=_upload("entities.jsonl", ent_file),
                                           session=s, principal=admin)
            check(doc.status == "ready" and doc.chunk_count == 3, f"V3c 정상 업로드 ready 3청크 (got {doc.status}/{doc.chunk_count})")
        async with async_session() as s:
            chunks = (await s.execute(select(Chunk).where(Chunk.collection_id == col_id).order_by(Chunk.ordinal))).scalars().all()
            check(len(chunks) == 3 and chunks[0].meta == {"pid": 1, "order_id": "o-1"},
                  "V3d 1행=1청크 + meta 저장")
            check("name: 무선 키보드 1" in chunks[0].text, f"V3e 임베딩 텍스트=평탄화: {chunks[0].text[:40]!r}")

        # ---- V4 검색 ----
        async with async_session() as s:
            rc = await RG.resolve_search_collection(s, col_id)
        hits = await RT.search_collections([rc], "무선 키보드", 3)
        check(len(hits) >= 1 and isinstance(hits[0].get("meta"), dict) and "pid" in hits[0]["meta"],
              f"V4a 엔티티 hit meta 동반: {hits[0].get('meta')}")
        async with async_session() as s:
            docs_kb = (await s.execute(select(Collection).where(Collection.name == "docs-kb"))).scalar_one_or_none()
            if docs_kb is not None:
                rc2 = await RG.resolve_search_collection(s, docs_kb.id)
                hits2 = await RT.search_collections([rc2], "에이전트 만들기", 2)
                check(all(h.get("meta") is None for h in hits2), "V4b 문서형 hit meta=None(무회귀)")
            else:
                check(True, "V4b (docs-kb 없음 — 스킵)")

        # ---- V5 도구 포맷 ----
        txt = RT.format_rag_hits(hits)
        check("[metadata:" in txt and "pid" in txt, f"V5a 도구 포맷에 metadata 포함")
        txt2 = RT.format_rag_hits([{"score": 0.9, "filename": "a.md", "text": "본문", "meta": None}])
        check("[metadata:" not in txt2, "V5b 문서형 포맷 무변화")
    finally:
        async with async_session() as s:
            for name in (f"{tag}-entities", f"{tag}-bad", f"{tag}-doc-schema"):
                c = (await s.execute(select(Collection).where(Collection.name == name))).scalar_one_or_none()
                if c is not None:
                    await s.delete(c)  # Document/Chunk CASCADE
            await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())
