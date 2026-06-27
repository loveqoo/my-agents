"""mem0 백엔드 어댑터 — `MemoryBackend`를 mem0 2.0.7로 구현. 스펙 040 (P4).

mem0 라이브러리 결합은 **이 모듈에만** 격리된다(`import mem0`도 여기서만). 벡터 스토어는 공유
Postgres(pgvector) — DATABASE_URL에서 파생(스펙 019). LLM·임베딩은 등록 모델 레지스트리에서
해석된 mem_cfg로 받는다(env 미참조).

**축별 병합은 mem0 고유 우회**: mem0 필터는 AND라 여러 축을 한 질의에 넘기면 교집합이 된다.
"유저 사실 ∪ 세션 사실"의 합집합 회상을 위해 **축별로 따로 검색해 병합**한다(id dedup, score 정렬).
이는 `MemoryBackend.search`/`list_all` 계약(합집합 회상)을 mem0로 *구현*하는 방식일 뿐이다.

mem_cfg = {"llm": {base_url, api_key, model_id}, "embedder": {base_url, api_key, model_id}}.
지배 스펙: 007(Phase 2), 008(레지스트리), 019(pgvector), 020(스코프), 040(추상화).
"""

import logging
import os

from .backend import scope_axes

log = logging.getLogger("api.memory")

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


class Mem0Backend:
    """mem0 Memory 인스턴스를 감싸 `MemoryBackend` 계약을 구현. 생성 실패는 호출자(resolve_backend)가 흡수."""

    def __init__(self, mem_cfg: dict):
        from mem0 import Memory  # 지연 임포트 — mem0 결합을 이 모듈에 가둠

        self._mem = Memory.from_config(_build_config(mem_cfg))
        log.info("mem0 initialized (registry models)")

    def search(self, scope: dict, query: str, limit: int) -> list[dict]:
        axes = scope_axes(scope)
        if not query or not axes:
            return []
        merged: dict[str, dict] = {}
        for axis, val in axes:
            try:
                # mem0 2.0.7 search는 top_k= 를 받는다(limit=는 **kwargs로 삼켜져 무시됨, 기본 20 → 과다 fetch).
                res = self._mem.search(query=query, filters={axis: val}, top_k=limit)
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

    def add(self, scope: dict, messages: list[dict], infer: bool) -> None:
        kwargs = {axis: val for axis, val in scope_axes(scope)}
        if not messages or not kwargs:
            return
        try:
            self._mem.add(messages, infer=infer, **kwargs)
        except Exception as exc:
            log.warning("mem0 add failed: %s", exc)

    def list_all(self, scope: dict) -> list[dict]:
        axes = scope_axes(scope)
        if not axes:
            return []
        merged: dict[str, dict] = {}
        for axis, val in axes:
            try:
                res = self._mem.get_all(filters={axis: val})
            except Exception as exc:
                log.warning("mem0 get_all failed (%s): %s", axis, exc)
                continue
            rows = res.get("results", res) if isinstance(res, dict) else res
            for r in rows or []:
                mem_id = r.get("id")
                if not mem_id:
                    continue
                merged[mem_id] = {"id": mem_id, "text": r.get("memory") or r.get("text") or ""}
        return list(merged.values())

    def update(self, mem_id: str, text: str) -> bool:
        if not mem_id:
            return False
        try:
            self._mem.update(memory_id=mem_id, data=text)
            return True
        except Exception as exc:
            log.warning("mem0 update failed: %s", exc)
            return False

    def delete(self, mem_id: str) -> bool:
        if not mem_id:
            return False
        try:
            self._mem.delete(memory_id=mem_id)
            return True
        except Exception as exc:
            log.warning("mem0 delete failed: %s", exc)
            return False
