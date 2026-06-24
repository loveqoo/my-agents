"""Mem0 장기 메모리 래퍼 (스코프별 의미론적 메모리).

스코프 키(`scope_id`)는 호출자(chat.py)가 정한다 — userId(유저 장기) 또는 session_id(세션 단기).
mem0의 `user_id` 축에 이 scope_id를 그대로 싣는다(누구의 기억인가 = 세션 가로지름 여부).

LLM·임베딩 모델은 **등록된 모델 레지스트리**에서 해석해 호출자(chat.py)가 mem_cfg로 넘긴다.
env(MLX_*)는 보지 않는다. 벡터 스토어는 임베디드 qdrant(on-disk).
설정/런타임 오류는 모두 흡수해 graceful 무력화 — 메모리가 없어도 채팅은 동작.

mem_cfg = {
  "llm":      {"base_url", "api_key", "model_id"},
  "embedder": {"base_url", "api_key", "model_id"},
}
지배 스펙: docs/spec/007(Phase 2), 008(모델 레지스트리)
"""

import logging
import os

log = logging.getLogger("api.memory")

SEMANTIC_MEMORY = "장기·의미론적"
_EMBED_DIMS = 1024  # multilingual-e5-large

# mem_cfg 키별로 Memory 인스턴스를 캐시 (모델이 바뀌면 재생성). 값 None = 초기화 실패.
_cache: dict[tuple, object | None] = {}


def memory_enabled(memories: list[str]) -> bool:
    """에이전트가 '장기·의미론적' 메모리를 켰는지."""
    return SEMANTIC_MEMORY in (memories or [])


def _cfg_key(mem_cfg: dict) -> tuple:
    # api_key까지 키에 포함 — 키 회전/자격 변경 시 stale 인스턴스 재사용 방지(codex P1).
    # 프로세스 메모리 내 캐시 키일 뿐이며 로깅하지 않는다.
    llm = mem_cfg.get("llm") or {}
    emb = mem_cfg.get("embedder") or {}
    return (
        llm.get("base_url"), llm.get("model_id"), llm.get("api_key"),
        emb.get("base_url"), emb.get("model_id"), emb.get("api_key"),
    )


def _build_config(mem_cfg: dict) -> dict:
    llm = mem_cfg["llm"]
    emb = mem_cfg["embedder"]
    qdrant_path = os.environ.get("MEM0_QDRANT_PATH", os.path.abspath(".dev/mem0_qdrant"))
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": llm["model_id"],
                "openai_base_url": llm["base_url"],
                "api_key": llm.get("api_key") or "sk-noauth",
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": emb["model_id"],
                "openai_base_url": emb["base_url"],
                "api_key": emb.get("api_key") or "sk-noauth",
                "embedding_dims": _EMBED_DIMS,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {"path": qdrant_path, "embedding_model_dims": _EMBED_DIMS, "on_disk": True},
        },
    }


def _get_memory(mem_cfg: dict | None):
    """mem_cfg(레지스트리 모델)로 Memory 인스턴스 확보. 캐시·graceful 무력화."""
    if not mem_cfg or not mem_cfg.get("llm") or not mem_cfg.get("embedder"):
        return None
    key = _cfg_key(mem_cfg)
    if key in _cache:
        return _cache[key]
    try:
        from mem0 import Memory  # 지연 임포트

        mem = Memory.from_config(_build_config(mem_cfg))
        log.info("mem0 initialized (registry models)")
        _cache[key] = mem
        return mem
    except Exception as exc:  # 설정/런타임 오류 → graceful 무력화
        log.warning("mem0 init failed, memory disabled: %s", exc)
        _cache[key] = None
        return None


def search(scope_id: str, query: str, mem_cfg: dict | None, limit: int = 4) -> list[dict]:
    """관련 메모리 top-k. 트레이스용 [{type, text, score}]. 실패/무력화 시 []."""
    mem = _get_memory(mem_cfg)
    if mem is None or not query:
        return []
    try:
        res = mem.search(query=query, filters={"user_id": scope_id}, limit=limit)
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


def add(scope_id: str, messages: list[dict], mem_cfg: dict | None) -> None:
    """대화 턴을 메모리에 저장. 실패/무력화 시 무시."""
    mem = _get_memory(mem_cfg)
    if mem is None or not messages:
        return
    try:
        mem.add(messages, user_id=scope_id)
    except Exception as exc:
        log.warning("mem0 add failed: %s", exc)
