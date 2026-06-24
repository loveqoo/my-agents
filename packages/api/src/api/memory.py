"""Mem0 장기 메모리 래퍼 (다층 스코프 — 유저/세션).

스코프는 호출자(chat.py)가 **dict로** 정한다: `{"user_id", "agent_id", "run_id"}`(None 허용).
mem0의 세 스코프 축에 각각 싣는다 — `user_id`=유저 사실(세션 가로지름), `run_id`=세션 단기.
`agent_id`(에이전트 전용 메모리)는 시그니처에 자리만 예약 — 이번 스펙(020)에서는 항상 None,
안전한 쓰기 채널 확정 후 후속 스펙에서 채운다.

mem0 필터는 **AND**다(여러 축을 한 질의에 넘기면 교집합). 따라서 "유저 사실 ∪ 세션 사실"의
합집합 회상은 **축별로 따로 검색해 병합**한다(id dedup, score 정렬). 풍부 태깅된 기억은
부분집합 필터로도 회상되므로, add 때 user_id+run_id를 함께 태깅하면 양쪽 검색에 잡힌다(스펙 020).

LLM·임베딩 모델은 **등록된 모델 레지스트리**에서 해석해 호출자(chat.py)가 mem_cfg로 넘긴다.
env(MLX_*)는 보지 않는다. 벡터 스토어는 **공유 Postgres(pgvector)** — DATABASE_URL에서
파생(스펙 019). N-인스턴스에서 같은 기억을 회상하려면 벡터 스토어가 공유돼야 한다.
설정/런타임 오류는 모두 흡수해 graceful 무력화 — 메모리가 없어도 채팅은 동작.

mem_cfg = {
  "llm":      {"base_url", "api_key", "model_id"},
  "embedder": {"base_url", "api_key", "model_id"},
}
지배 스펙: docs/spec/007(Phase 2), 008(모델 레지스트리), 020(다층 스코프)
"""

import logging
import os

log = logging.getLogger("api.memory")

# 카탈로그에서 mem0 장기 메모리를 켜는 토글 이름(seed.py MEMORY_TYPES와 동일해야 함).
LONG_TERM_MEMORY = "장기 기억 (mem0)"
# 스코프 축 우선순위(검색 병합·태깅 순서). agent_id는 후속 스펙까지 항상 None.
_SCOPE_AXES = ("user_id", "run_id", "agent_id")
# pgvector 테이블 차원은 생성 시 고정된다 — 기본 임베딩 모델(레지스트리)의 출력 차원과 반드시 일치해야 한다.
# 불일치 시 insert가 깨지고 mem0 add는 except로 삼켜 메모리가 조용히 죽는다(스펙 019). 현재 기본
# multilingual-e5-large=1024(라이브 probe로 검증). 기본 임베딩 모델을 바꾸면 이 값(또는 env)을 맞춰라.
_EMBED_DIMS = int(os.environ.get("MEM0_EMBED_DIMS", "1024"))
_MEM_TABLE = "mem0_memories"  # mem0 전용 테이블(앱 테이블과 공존, 관리 주체는 mem0)


def _sync_dsn(url: str) -> str:
    """DATABASE_URL의 드라이버 접미사만 제거해 psycopg용 DSN으로 — 그 외는 손대지 않는다.

    'postgresql+asyncpg://...' → 'postgresql://...'. authority·쿼리스트링(sslmode 등)·
    퍼센트 인코딩은 **그대로 보존**하여 psycopg(libpq)가 표준대로 파싱하게 위임한다.
    (분해→재조립하면 자격정보 부재 시 'None' 인증, raw 특수문자 오파싱 등이 생긴다 — 타자 검증 P1.)
    """
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme.split('+', 1)[0]}://{rest}"


def _pg_vector_store() -> dict:
    """mem0 벡터 스토어를 기존 Postgres(pgvector)로 — DATABASE_URL 단일 출처에서.

    on-disk qdrant는 인스턴스 로컬이라 N-인스턴스에서 기억이 파편화된다(스펙 019).
    pgvector는 공유 Postgres에 저장하므로 모든 인스턴스가 같은 기억을 회상한다.
    mem0 PGVector는 connection_string을 개별 파라미터보다 우선한다(소스 확인) → raw DSN을
    그대로 위임(search/add는 to_thread 호출이라 동기 psycopg 풀과 이벤트루프 충돌 없음).
    """
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents")
    return {
        "provider": "pgvector",
        "config": {
            "connection_string": _sync_dsn(url),
            "collection_name": _MEM_TABLE,
            "embedding_model_dims": _EMBED_DIMS,
            "hnsw": True,
        },
    }

# mem_cfg 키별로 Memory 인스턴스를 캐시 (모델이 바뀌면 재생성). 값 None = 초기화 실패.
_cache: dict[tuple, object | None] = {}


def memory_enabled(memories: list[str]) -> bool:
    """에이전트가 mem0 장기 메모리(`장기 기억 (mem0)`)를 켰는지."""
    return LONG_TERM_MEMORY in (memories or [])


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
        "vector_store": _pg_vector_store(),
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


def _scope_axes(scope: dict) -> list[tuple[str, str]]:
    """스코프 dict에서 None이 아닌 (축, 값) 쌍만 우선순위 순으로."""
    return [(axis, scope.get(axis)) for axis in _SCOPE_AXES if scope.get(axis)]


def search(scope: dict, query: str, mem_cfg: dict | None, limit: int = 4) -> list[dict]:
    """관련 메모리 top-k. 트레이스용 [{type, text, score, scope}]. 실패/무력화 시 [].

    스코프 축마다 **따로** 검색해 합집합으로 병합한다(mem0 필터는 AND이므로 — 모듈 docstring 참고).
    같은 기억이 여러 축(예: user_id+run_id 태깅)에 잡히면 id로 dedup하고 더 높은 score를 남긴다.
    """
    mem = _get_memory(mem_cfg)
    axes = _scope_axes(scope)
    if mem is None or not query or not axes:
        return []
    merged: dict[str, dict] = {}
    for axis, val in axes:
        try:
            # mem0 2.0.7 search는 top_k= 를 받는다(limit=는 **kwargs로 삼켜져 무시됨, 기본 20 → 과다 fetch).
            res = mem.search(query=query, filters={axis: val}, top_k=limit)
        except Exception as exc:
            log.warning("mem0 search failed (%s): %s", axis, exc)
            continue
        rows = res.get("results", res) if isinstance(res, dict) else res
        for r in rows or []:
            text = r.get("memory") or r.get("text") or ""
            score = round(float(r.get("score", 0.0)), 3)
            # id가 없으면 본문으로 대체 키 — 같은 본문이 다른 축에서 중복 카운트되지 않게(축 접두사 없이).
            key = r.get("id") or text
            prev = merged.get(key)
            if prev is None or score > prev["score"]:
                merged[key] = {"type": "semantic", "text": text, "score": score, "scope": axis}
    hits = sorted(merged.values(), key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def add(scope: dict, messages: list[dict], mem_cfg: dict | None) -> None:
    """대화 턴을 메모리에 저장. 실패/무력화 시 무시.

    제공된 모든 축(user_id/run_id/…)을 **한 번에** 태깅한다 — 풍부 태깅된 기억은 이후 부분집합
    필터(축별 검색)로 양쪽에서 회상된다(스펙 020). 축이 하나도 없으면 저장하지 않는다.
    """
    mem = _get_memory(mem_cfg)
    kwargs = {axis: val for axis, val in _scope_axes(scope)}
    if mem is None or not messages or not kwargs:
        return
    try:
        mem.add(messages, **kwargs)
    except Exception as exc:
        log.warning("mem0 add failed: %s", exc)
