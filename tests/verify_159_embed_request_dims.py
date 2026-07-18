"""verify_159 — mem0가 임베더에 차원을 강제해 self-hosted 임베더가 400 (스펙 159).

근인: _build_config가 임베더에 embedding_dims=_EMBED_DIMS를 넣어 mem0가 요청에 dimensions=1024를
강제 전송 → snowflake 등 dimensions 거부 서버가 400. 수정: 네이티브 차원을 probe해 판단
(네이티브==컬럼→미전송, 네이티브≠컬럼→절단 요청; codex 159 High: 정적 기본값은 한쪽을 깸).

  V1 네이티브==컬럼(snowflake): embedding_dims 미포함 → _pass_dimensions_to_api=False.
  V2 네이티브≠컬럼(text-embedding-3류 1536): embedding_dims=_EMBED_DIMS 전송 → _pass=True(회귀 방지).
  V3 opt-in env(MEM0_EMBED_REQUEST_DIMS): 그 값 전송(probe 무관).
  V4 probe 실패: 미전송(보수적).
  V5 로컬 add+search 왕복(실 probe, mock 네이티브==컬럼) 동작. V6 컬럼 차원 불변.
실행: uv run --project packages/api --env-file .env python tests/verify_159_embed_request_dims.py
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
from mem0.configs.embeddings.base import BaseEmbedderConfig  # noqa: E402
from mem0.embeddings.openai import OpenAIEmbedding  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _pass_dims_flag(emb_config: dict) -> bool:
    """임베더 config로 실제 mem0 OpenAIEmbedding을 만들어 요청에 dimensions가 실리는지 측정."""
    c = emb_config["config"]
    cfg = BaseEmbedderConfig(
        model=c["model"],
        api_key=c.get("api_key"),
        openai_base_url=c.get("openai_base_url"),
        embedding_dims=c.get("embedding_dims"),
    )
    return OpenAIEmbedding(cfg)._pass_dimensions_to_api


FAKE = {
    "llm": {"model_id": "L", "base_url": "http://x/v1", "api_key": "k"},
    "embedder": {
        "model_id": "snowflake-arctic-embed-l-v2.0",
        "base_url": "http://x/v1",
        "api_key": "k",
    },
}


def _build_with_native(native, request_env=None):
    """_native_embed_dims를 native로 고정하고 _build_config 결과를 반환(캐시·env 복원)."""
    orig_probe = mem0_backend._native_embed_dims
    orig_env = mem0_backend._EMBED_REQUEST_DIMS
    mem0_backend._native_embed_dims = lambda emb: native
    mem0_backend._EMBED_REQUEST_DIMS = request_env
    try:
        return mem0_backend._build_config(FAKE)
    finally:
        mem0_backend._native_embed_dims = orig_probe
        mem0_backend._EMBED_REQUEST_DIMS = orig_env


async def main():
    col = mem0_backend._EMBED_DIMS  # 컬럼 차원(1024)

    # ---- V1 네이티브==컬럼 → 미전송 ----
    c1 = _build_with_native(col)
    check(
        "embedding_dims" not in c1["embedder"]["config"],
        "V1a 네이티브==컬럼: embedding_dims 미포함",
    )
    check(
        _pass_dims_flag(c1["embedder"]) is False,
        "V1b 네이티브==컬럼: dimensions 미전송(snowflake 안전)",
    )

    # ---- V2 네이티브≠컬럼(1536) → 컬럼 길이로 전송 ----
    c2 = _build_with_native(1536)
    check(
        c2["embedder"]["config"].get("embedding_dims") == col,
        f"V2a 네이티브≠컬럼: embedding_dims={col} 전송(절단 의도) (got {c2['embedder']['config'].get('embedding_dims')})",
    )
    check(
        _pass_dims_flag(c2["embedder"]) is True,
        "V2b 네이티브≠컬럼: dimensions 전송(text-embedding-3 회귀 방지)",
    )

    # ---- V3 opt-in env override(int 상수) ----
    c3 = _build_with_native(col, request_env=256)
    check(
        c3["embedder"]["config"].get("embedding_dims") == 256,
        f"V3 opt-in env: embedding_dims=256(probe 무관) (got {c3['embedder']['config'].get('embedding_dims')})",
    )

    # ---- V4 probe 실패 → 미전송 ----
    c4 = _build_with_native(None)
    check("embedding_dims" not in c4["embedder"]["config"], "V4 probe 실패: 미전송(보수적)")

    # ---- V6 컬럼 차원 불변 ----
    check(
        c1["vector_store"]["config"]["embedding_model_dims"] == col,
        f"V6 컬럼 차원 _EMBED_DIMS 불변 (got {c1['vector_store']['config']['embedding_model_dims']})",
    )

    # ---- V7 env 검증(codex 159b Low): 비정수/≤0/빈값 → None(무시), 양수 → int ----
    pi = mem0_backend._env_positive_int
    os.environ["_V159_T"] = "abc"
    check(pi("_V159_T") is None, "V7a 비정수 env → None(ValueError 방지)")
    os.environ["_V159_T"] = "0"
    check(pi("_V159_T") is None, "V7b '0' → None(dimensions=0 방지)")
    os.environ["_V159_T"] = "-5"
    check(pi("_V159_T") is None, "V7c 음수 → None")
    os.environ["_V159_T"] = "512"
    check(pi("_V159_T") == 512, "V7d 양수 → int")
    os.environ.pop("_V159_T", None)
    check(pi("_V159_T") is None, "V7e 미설정 → None")

    # ---- V8 캐시 키에 api_key 포함(codex 159b High): 다른 키는 다른 엔트리 ----
    base, mid = "http://unreachable-v159/v1", "m"
    mem0_backend._native_dims_cache[(base, mid, "keyA")] = 4242  # keyA 사전 시드
    check(
        mem0_backend._native_embed_dims({"base_url": base, "model_id": mid, "api_key": "keyA"})
        == 4242,
        "V8a keyA 캐시 히트",
    )
    # keyB(다른 api_key)는 캐시 미스 → 도달 불가 URL probe 실패 → None(4242 아님 = 키 분리 증명)
    check(
        mem0_backend._native_embed_dims({"base_url": base, "model_id": mid, "api_key": "keyB"})
        != 4242,
        "V8b keyB(다른 api_key)는 keyA 엔트리를 안 씀(캐시 키에 api_key 포함)",
    )
    mem0_backend._native_dims_cache.pop((base, mid, "keyA"), None)
    mem0_backend._native_dims_cache.pop((base, mid, "keyB"), None)

    # ---- V5 로컬 add+search 왕복(실 probe) ----
    from api.mem_config import default_mem_cfg
    from api.db import SessionLocal

    async with SessionLocal() as db:
        mem_cfg = await default_mem_cfg(db)
    backend = memory.resolve_backend(mem_cfg)
    if backend is None or type(backend).__name__ != "Mem0Backend":
        check(True, "V5 skip — 로컬 mem0 백엔드 미가용")
    else:
        scope = {"user_id": f"v159-{_uuid.uuid4().hex[:8]}"}
        try:
            backend.add(
                scope, [{"role": "user", "content": "The Agent ABCD framework note"}], infer=False
            )
            await asyncio.sleep(1)
            hits = backend.search(scope, "The Agent ABCD framework note", 4, threshold=0.0)
            check(
                len(hits) >= 1,
                f"V5 실 probe로 add+search 왕복 동작(mock 네이티브==컬럼) (got {len(hits)})",
            )
        finally:
            import psycopg

            dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
            with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
                cur.execute(
                    "DELETE FROM mem0_memories WHERE payload->>'user_id' = %s", (scope["user_id"],)
                )

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())
