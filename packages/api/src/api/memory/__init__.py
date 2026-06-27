"""장기 메모리 facade — 백엔드 추상화 뒤로 위임. 스펙 040 (P4, 로드맵 #7).

공개 표면(외부 소비자 = chat/runtime/agents/memory_routes/batch.jobs)은 **무변경**으로 보존한다:
`memory_enabled`, `search`, `add`, `list_memories`, `update_memory`, `delete_memory`. 각 함수는
`resolve_backend(mem_cfg)`로 백엔드(기본 mem0)를 확보해 위임하고, 백엔드가 없으면(설정 미비/초기화
실패) 안전 기본값을 돌린다 — 메모리가 없어도 채팅·관리가 동작(스펙 019).

스코프는 호출자가 dict로 정한다: {"user_id", "agent_id", "run_id"}(None 허용). user_id=유저 사실
(세션 가로지름), run_id=세션 단기, agent_id=에이전트 전용(029, 의도적 채널만). 합집합 회상·축별
의미·infer 규칙은 각 백엔드가 계약(`memory/backend.py: MemoryBackend`)대로 구현한다.

mem_cfg = {"llm": {base_url, api_key, model_id}, "embedder": {base_url, api_key, model_id}}.
백엔드 선택은 `MEMORY_BACKEND` env(기본 "mem0"). 지배 스펙: 007/008/019/020/040.
"""

from .backend import MemoryBackend, resolve_backend, scope_axes  # noqa: F401  (재노출)

# 카탈로그에서 mem0 장기 메모리를 켜는 토글 이름(seed.py MEMORY_TYPES와 동일해야 함).
LONG_TERM_MEMORY = "장기 기억 (mem0)"


def memory_enabled(memories: list[str]) -> bool:
    """에이전트가 장기 메모리(`장기 기억 (mem0)`)를 켰는지. 순수 함수(백엔드 무관)."""
    return LONG_TERM_MEMORY in (memories or [])


def search(scope: dict, query: str, mem_cfg: dict | None, limit: int = 4) -> list[dict]:
    """관련 메모리 top-k. [{type, text, score, scope}]. 무력화/실패 시 []."""
    backend = resolve_backend(mem_cfg)
    return backend.search(scope, query, limit) if backend else []


def add(scope: dict, messages: list[dict], mem_cfg: dict | None, infer: bool = True) -> None:
    """대화 턴/사실을 메모리에 저장. 무력화/실패 시 무시.

    infer: True(기본)면 백엔드가 사실을 추출·통합(mem0 기본). False면 messages 본문을 원문 그대로
    저장(스펙 029 — 에이전트 자가기록·관리자 저작처럼 이미 정제된 한 줄 사실용).
    """
    backend = resolve_backend(mem_cfg)
    if backend:
        backend.add(scope, messages, infer)


def list_memories(scope: dict, mem_cfg: dict | None) -> list[dict]:
    """스코프 축의 모든 기억 [{id, text}]. 무력화/실패 시 []. (관리자 큐레이션·스펙 029/030)"""
    backend = resolve_backend(mem_cfg)
    return backend.list_all(scope) if backend else []


def update_memory(mem_id: str, text: str, mem_cfg: dict | None) -> bool:
    """기억 본문 수정. 성공 True / 실패·무력화 False. (스펙 029)"""
    backend = resolve_backend(mem_cfg)
    return backend.update(mem_id, text) if backend else False


def delete_memory(mem_id: str, mem_cfg: dict | None) -> bool:
    """기억 삭제. 성공 True / 실패·무력화 False. (스펙 029)"""
    backend = resolve_backend(mem_cfg)
    return backend.delete(mem_id) if backend else False
