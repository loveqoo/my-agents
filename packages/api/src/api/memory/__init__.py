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


def format_memory_hits(hits: list[dict]) -> str:
    """회상 히트를 텍스트 블록으로(챗 회상 주입·브로커 memory 능력 공유 포맷, 스펙 104 drift 0).

    챗은 이 문자열을 페르소나 프롬프트의 `# 관련 기억(회상됨)` 섹션에, 브로커는 InvokeResult.text로
    쓴다 — 한 곳에서 포맷해 두 입구가 같은 표현을 갖는다(103 format_rag_hits와 동형).

    **이건 격리 장치가 아니라 순수 문자열 결합이다**(적대 리뷰 104 P2 명시화). "결과=데이터(지시 아님)"의
    보장은 *여기서 안 생기고* 소비 측 채널 조립에 달렸다: 브로커 위임 경로는 flow가 결과를 라벨 붙은
    별도 Human 데이터 채널(`build_synthesis_messages`, learning 100)로 감싸 system 지침과 격리한다.
    챗 직접 회상 경로는 회상 사실을 persona 프롬프트에 합치는데(스펙 104 이전부터의 설계, 자기 user_id
    기억 = 자기 대화서 추출된 자기 사실이라 교차유저 인젝션 아님) — 이 채널 결정은 104 밖이다."""
    return "\n".join(f"- {h['text']}" for h in (hits or []))


def recall_probe(scope: dict, query: str, mem_cfg: dict | None, limit: int = 4) -> list[dict] | None:
    """회상 *시험*용(스펙 084) — `search`와 같되 백엔드 **가용성**을 결과와 구분해 돌린다.

    백엔드 미가용(mem_cfg None·llm/embedder 누락·초기화 실패로 resolve_backend가 None 흡수) → None.
    가용 → top-k 리스트(limit로 방어적 슬라이스). `search`가 두 경우를 모두 []로 뭉개는 것과 다르다:
    시험 도구가 *구성됐으나 깨진* 백엔드를 "기억 없음(빈 results)"으로 오인하면 진단이 거짓이 된다
    (적대 리뷰 084 P2a). 호출자는 `hits is None`으로 enabled=False를, `[]`로 "가용·회상 0건"을
    구분한다. chat 경로(`search`)는 무변경 — drift 0."""
    backend = resolve_backend(mem_cfg)
    if backend is None:
        return None
    # limit 정수 강제 + 범위 clamp(적대 리뷰 104 P2). 엔드포인트는 스키마(1-10)로 막지만 브로커 위임
    # 경로는 args의 limit을 검증 없이 넘겨(`{"limit":"boom"}`) `[:limit]`에서 TypeError·`-1`로 꼬리절단
    # 될 수 있었다. 여기(084가 이미 방어 슬라이스를 둔 지점)서 한 번 정규화해 세 입구를 같은 경계로.
    n = _clamp_limit(limit)
    return backend.search(scope, query, n)[:n]


def _clamp_limit(limit) -> int:
    """recall 상한을 정수 [1,10]로 정규화(엔드포인트 스키마와 동일 경계). 비정수/음수/거대 방어."""
    try:
        return max(1, min(int(limit), 10))
    except (TypeError, ValueError):
        return 4


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
