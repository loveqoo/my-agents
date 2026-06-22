"""Mem0 장기 메모리 래퍼 (에이전트별 의미론적 메모리).

LLM·임베딩은 로컬 MLX(OpenAI 호환), 벡터 스토어는 임베디드 qdrant(on-disk).
설정/런타임 오류는 모두 흡수해 **graceful 무력화**한다 — 메모리가 없어도 채팅은 동작.
'장기·의미론적' 메모리를 켠 에이전트만 사용한다.

지배 스펙: docs/spec/007-real-agent-service.md (Phase 2)
"""

import logging
import os
from functools import lru_cache

log = logging.getLogger("api.memory")

SEMANTIC_MEMORY = "장기·의미론적"
_EMBED_DIMS = 1024  # mlx-community/multilingual-e5-large-mlx


def _build_config() -> dict:
    base_url = os.environ.get("MLX_BASE_URL", "http://localhost:8045/v1")
    api_key = os.environ.get("MLX_API_KEY", "")
    llm_model = os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8")
    embed_model = os.environ.get("MLX_EMBED_MODEL", "mlx-community/multilingual-e5-large-mlx")
    qdrant_path = os.environ.get("MEM0_QDRANT_PATH", os.path.abspath(".dev/mem0_qdrant"))
    # mem0의 openai 프로바이더는 OPENAI_* env도 참조 — 안전하게 같이 설정.
    os.environ.setdefault("OPENAI_API_KEY", api_key or "sk-local")
    os.environ.setdefault("OPENAI_BASE_URL", base_url)
    return {
        "llm": {
            "provider": "openai",
            "config": {"model": llm_model, "openai_base_url": base_url, "api_key": api_key},
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": embed_model,
                "openai_base_url": base_url,
                "api_key": api_key,
                "embedding_dims": _EMBED_DIMS,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {"path": qdrant_path, "embedding_model_dims": _EMBED_DIMS, "on_disk": True},
        },
    }


@lru_cache(maxsize=1)
def _get_memory():
    """Mem0 인스턴스 1회 초기화. 실패 시 None (무력화)."""
    if os.environ.get("MEM0_ENABLED", "true").lower() in {"0", "false", "no"}:
        log.info("mem0 disabled via MEM0_ENABLED")
        return None
    try:
        from mem0 import Memory  # 지연 임포트

        mem = Memory.from_config(_build_config())
        log.info("mem0 initialized (MLX llm/embed + embedded qdrant)")
        return mem
    except Exception as exc:  # 설정/런타임 오류 → graceful 무력화
        log.warning("mem0 init failed, memory disabled: %s", exc)
        return None


def memory_enabled(memories: list[str]) -> bool:
    """에이전트가 '장기·의미론적' 메모리를 켰는지."""
    return SEMANTIC_MEMORY in (memories or [])


def search(agent_id: str, query: str, limit: int = 4) -> list[dict]:
    """관련 메모리 top-k. 트레이스용 [{type, text, score}]. 실패/무력화 시 []."""
    mem = _get_memory()
    if mem is None or not query:
        return []
    try:
        # mem0 2.x: user_id 대신 filters={'user_id': ...}
        res = mem.search(query=query, filters={"user_id": agent_id}, limit=limit)
        rows = res.get("results", res) if isinstance(res, dict) else res
        hits: list[dict] = []
        for r in rows or []:
            hits.append(
                {
                    "type": "semantic",
                    "text": r.get("memory") or r.get("text") or "",
                    "score": round(float(r.get("score", 0.0)), 3),
                }
            )
        return hits
    except Exception as exc:
        log.warning("mem0 search failed: %s", exc)
        return []


def add(agent_id: str, messages: list[dict]) -> None:
    """대화 턴을 메모리에 저장. 실패/무력화 시 무시."""
    mem = _get_memory()
    if mem is None or not messages:
        return
    try:
        mem.add(messages, user_id=agent_id)
    except Exception as exc:
        log.warning("mem0 add failed: %s", exc)
