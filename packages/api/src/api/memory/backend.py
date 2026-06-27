"""메모리 백엔드 추상화 — Protocol + 선택·캐시. 스펙 040 (P4, 로드맵 #7).

facade(`memory/__init__.py`)는 이 모듈의 `resolve_backend(mem_cfg)`만 거쳐 백엔드에 위임한다.
구체 백엔드(mem0 등)는 `_BACKENDS` 레지스트리에 등록하고 **지연 임포트**한다 — facade가 mem0를
끌지 않게(격리). 새 백엔드 drop-in = 레지스트리 한 줄 + `MEMORY_BACKEND` env.

**스코프 단위 계약**: search는 스코프 전 축의 **합집합 회상**(id dedup, score 내림차순, top-k 절단,
hit에 scope축 태깅)을 보장한다. "mem0는 필터가 AND라 축별로 따로 검색해 병합"하는 것은 mem0 어댑터의
*내부 구현*이지 계약이 아니다 — 그래프DB는 union을 네이티브로 할 수 있다(learning 021).

지배 스펙: docs/spec/archive/040, 020(스코프), 019(공유 백엔드).
"""

import importlib
import logging
import os
from typing import Protocol, runtime_checkable

log = logging.getLogger("api.memory")

# 스코프 축 우선순위(검색 병합·태깅 순서). agent_id는 029에서 의도적 채널로만 채운다.
SCOPE_AXES = ("user_id", "run_id", "agent_id")


def scope_axes(scope: dict) -> list[tuple[str, str]]:
    """스코프 dict에서 None이 아닌 (축, 값) 쌍만 우선순위 순으로. 백엔드 공용 정책."""
    return [(axis, scope.get(axis)) for axis in SCOPE_AXES if scope.get(axis)]


@runtime_checkable
class MemoryBackend(Protocol):
    """메모리 백엔드 계약. 설정(mem_cfg)은 생성 시 박히고, 메서드는 스코프 단위로 동작한다.

    모든 메서드는 **graceful** — 백엔드 내부 오류는 흡수해 안전 기본값([] / None / False)을 돌려
    메모리가 없어도 채팅·관리가 동작하게 한다(스펙 019).
    """

    def search(self, scope: dict, query: str, limit: int) -> list[dict]:
        """스코프 합집합 top-k. [{type, text, score, scope}]. 빈 질의/스코프·실패 시 []."""
        ...

    def add(self, scope: dict, messages: list[dict], infer: bool) -> None:
        """대화/사실을 스코프 전 축에 태깅해 저장. 빈 스코프/메시지·실패 시 무시."""
        ...

    def list_all(self, scope: dict) -> list[dict]:
        """스코프 합집합의 모든 기억 [{id, text}]. 빈 스코프·실패 시 []."""
        ...

    def update(self, mem_id: str, text: str) -> bool:
        """기억 본문 수정. 성공 True / 실패·무력화 False."""
        ...

    def delete(self, mem_id: str) -> bool:
        """기억 삭제. 성공 True / 실패·무력화 False."""
        ...


# drop-in: 새 백엔드 = 여기 한 줄("모듈경로", "클래스명") + MEMORY_BACKEND env.
# 임포트는 지연(_construct에서) — facade가 mem0 등 무거운 의존을 끌지 않게.
_BACKENDS: dict[str, tuple[str, str]] = {
    "mem0": ("api.memory.mem0_backend", "Mem0Backend"),
    "inmemory": ("api.memory.inmemory_backend", "InMemoryBackend"),
}

# (백엔드 종류, mem_cfg 키)별 인스턴스 캐시. 값 None = 초기화 실패(graceful 무력화).
_cache: dict[tuple, MemoryBackend | None] = {}


def _backend_kind() -> str:
    return os.environ.get("MEMORY_BACKEND", "mem0")


def _cfg_key(mem_cfg: dict) -> tuple:
    # api_key까지 키에 포함 — 키 회전/자격 변경 시 stale 인스턴스 재사용 방지(codex P1).
    # 프로세스 메모리 내 캐시 키일 뿐이며 로깅하지 않는다.
    llm = mem_cfg.get("llm") or {}
    emb = mem_cfg.get("embedder") or {}
    return (
        llm.get("base_url"), llm.get("model_id"), llm.get("api_key"),
        emb.get("base_url"), emb.get("model_id"), emb.get("api_key"),
    )


def _construct(kind: str, mem_cfg: dict) -> MemoryBackend:
    spec = _BACKENDS.get(kind)
    if spec is None:
        raise ValueError(f"unknown MEMORY_BACKEND: {kind!r}")
    mod_name, cls_name = spec
    cls = getattr(importlib.import_module(mod_name), cls_name)
    return cls(mem_cfg)


def resolve_backend(mem_cfg: dict | None) -> MemoryBackend | None:
    """mem_cfg로 백엔드 인스턴스 확보. 캐시·graceful 무력화.

    mem_cfg가 비거나 llm/embedder가 없으면 None(메모리 비활성). 백엔드 초기화 실패도 None으로
    흡수하고 캐시한다 — 같은 설정으로 매 호출 재시도하지 않게.
    """
    if not mem_cfg or not mem_cfg.get("llm") or not mem_cfg.get("embedder"):
        return None
    kind = _backend_kind()
    key = (kind, _cfg_key(mem_cfg))
    if key in _cache:
        return _cache[key]
    try:
        backend: MemoryBackend | None = _construct(kind, mem_cfg)
    except Exception as exc:  # 설정/런타임 오류 → graceful 무력화
        log.warning("memory backend %r init failed, memory disabled: %s", kind, exc)
        backend = None
    _cache[key] = backend
    return backend


def _reset_cache() -> None:
    """테스트용 — 백엔드 인스턴스 캐시 비우기."""
    _cache.clear()
