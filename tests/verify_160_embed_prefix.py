"""verify_160 — mem0 임베딩 query/passage 접두어 주입(스펙 160).

비대칭 모델(e5·arctic)은 검색어=query 접두어, 문서=passage 접두어를 붙여야 정합. mem0는 memory_action을
무시하므로 embed/embed_batch를 감싸 주입. 기본 ""=no-op(무회귀).

  V1 기본(접두어 미설정): 래핑 안 함 → embed 원문 그대로.
  V2 query/passage 설정: search=query 접두어, add/update=passage 접두어가 실제 텍스트에 붙음.
  V3 embed_batch도 action별 접두어 적용.
  V4 arctic 모사(passage 빈값·query만): 저장(add) 텍스트 무변경, 검색만 접두어(기존 raw 저장과 정합).
  V5 로컬 실 e5 add+search 왕복(접두어 설정) 동작(무회귀).
실행: uv run --project packages/api --env-file .env python tests/verify_160_embed_prefix.py
"""

import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

from api import memory  # noqa: E402
from api.memory import mem0_backend  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _SpyEmbedder:
    """embed/embed_batch가 받은 텍스트를 기록하는 스파이."""

    def __init__(self):
        self.seen = []  # (kind, text/texts, action)

    def embed(self, text, memory_action=None):
        self.seen.append(("embed", text, memory_action))
        return [0.0]

    def embed_batch(self, texts, memory_action="add"):
        self.seen.append(("batch", list(texts), memory_action))
        return [[0.0] for _ in texts]


class _FakeMem:
    def __init__(self):
        self.embedding_model = _SpyEmbedder()


def _wrap_with(qp, pp):
    """접두어 env를 세팅하고 _FakeMem을 래핑해 스파이를 반환(env 복원)."""
    oq, op = mem0_backend._QUERY_PREFIX, mem0_backend._PASSAGE_PREFIX
    mem0_backend._QUERY_PREFIX, mem0_backend._PASSAGE_PREFIX = qp, pp
    m = _FakeMem()
    try:
        mem0_backend._wrap_embedder_prefixes(m)
    finally:
        mem0_backend._QUERY_PREFIX, mem0_backend._PASSAGE_PREFIX = oq, op
    return m.embedding_model


async def main():
    # ---- V1 기본: 래핑 안 함 ----
    em1 = _wrap_with("", "")
    em1.embed("hello", "search")
    check(em1.seen[-1] == ("embed", "hello", "search"), "V1 접두어 미설정: 원문 그대로(래핑 no-op)")

    # ---- V2 query/passage 주입 ----
    em2 = _wrap_with("query: ", "passage: ")
    em2.embed("고양이", "search")
    em2.embed("강아지", "add")
    em2.embed("수정", "update")
    check(em2.seen[0] == ("embed", "query: 고양이", "search"), "V2a search → query 접두어")
    check(em2.seen[1] == ("embed", "passage: 강아지", "add"), "V2b add → passage 접두어")
    check(em2.seen[2] == ("embed", "passage: 수정", "update"), "V2c update → passage 접두어")

    # ---- V3 embed_batch ----
    em3 = _wrap_with("query: ", "passage: ")
    em3.embed_batch(["a", "b"], "add")
    em3.embed_batch(["c"], "search")
    check(
        em3.seen[0] == ("batch", ["passage: a", "passage: b"], "add"),
        "V3a batch add → passage 접두어",
    )
    check(em3.seen[1] == ("batch", ["query: c"], "search"), "V3b batch search → query 접두어")

    # ---- V4 arctic 모사(passage 빈값·query만) ----
    em4 = _wrap_with("query: ", "")
    em4.embed("문서저장", "add")
    em4.embed("검색어", "search")
    check(
        em4.seen[0] == ("embed", "문서저장", "add"),
        "V4a arctic: 저장 텍스트 무변경(passage raw, 기존 11건 정합)",
    )
    check(em4.seen[1] == ("embed", "query: 검색어", "search"), "V4b arctic: 검색만 query 접두어")

    # ---- V5 로컬 실 e5 왕복(접두어 설정) ----
    oq, op = mem0_backend._QUERY_PREFIX, mem0_backend._PASSAGE_PREFIX
    mem0_backend._QUERY_PREFIX, mem0_backend._PASSAGE_PREFIX = "query: ", "passage: "
    try:
        from api.mem_config import default_mem_cfg
        from api.db import SessionLocal

        async with SessionLocal() as db:
            mem_cfg = await default_mem_cfg(db)
        backend = memory.resolve_backend(mem_cfg)  # __init__이 래핑 적용
        if backend is None or type(backend).__name__ != "Mem0Backend":
            check(True, "V5 skip — 로컬 mem0 백엔드 미가용")
        else:
            scope = {"user_id": f"v160-{_uuid.uuid4().hex[:8]}"}
            try:
                backend.add(
                    scope, [{"role": "user", "content": "강아지를 키우고 있어요"}], infer=False
                )
                await asyncio.sleep(1)
                hits = backend.search(scope, "반려견과 함께 삽니다", 3, threshold=0.0)
                check(
                    len(hits) >= 1 and "강아지" in hits[0]["text"],
                    f"V5 접두어 설정 실 e5 add+search 왕복·의미매칭 동작 (top={hits[0]['text'] if hits else None})",
                )
            finally:
                import psycopg

                dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
                with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
                    cur.execute(
                        "DELETE FROM mem0_memories WHERE payload->>'user_id' = %s",
                        (scope["user_id"],),
                    )
    finally:
        mem0_backend._QUERY_PREFIX, mem0_backend._PASSAGE_PREFIX = oq, op

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())
