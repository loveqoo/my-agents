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

import logging
import re as _re

from .backend import MemoryBackend, resolve_backend, scope_axes  # noqa: F401  (재노출)

_log = logging.getLogger("api.memory")

# 카탈로그에서 mem0 장기 메모리를 켜는 토글 이름(seed.py MEMORY_TYPES와 동일해야 함).
LONG_TERM_MEMORY = "장기 기억 (mem0)"


def memory_enabled(memories: list[str]) -> bool:
    """에이전트가 장기 메모리(`장기 기억 (mem0)`)를 켰는지. 순수 함수(백엔드 무관)."""
    return LONG_TERM_MEMORY in (memories or [])


def search(scope: dict, query: str, mem_cfg: dict | None, limit: int = 4) -> list[dict]:
    """관련 메모리 top-k(챗 회상). [{type, text, score, scope}]. 무력화/실패 시 [].

    챗 경로는 **견고**해야 한다(회상 실패가 대화 턴을 500내면 안 됨) — backend.search가 전 축 실패로
    던지면(스펙 158) 여기서 흡수해 []. 실패의 *표면화*는 진단(recall_diag)·브로커(InvokeResult.error)
    담당이고, 챗은 조용히 회상 없이 진행한다."""
    backend = resolve_backend(mem_cfg)
    if not backend:
        return []
    try:
        return backend.search(scope, query, limit)
    except Exception as exc:  # noqa: BLE001 — 챗 회상은 견고(무회귀)
        # 타입명만 로그(스펙 158, codex High) — 예외 메시지에 임베더 비밀이 섞일 수 있어 raw 금지.
        _log.warning("memory.search failed — chat recall skipped: %s", type(exc).__name__)
        return []


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
    구분한다. chat 경로(`search`)는 무변경 — drift 0.

    스펙 158: backend.search가 전 축 실패로 **던지면 그대로 전파**한다(여기선 안 삼킴). 브로커
    `invoke`가 이 예외를 잡아 `InvokeResult.error`로 표면화한다 — []로 접으면 recall_probe가 막으려던
    "실패를 0건으로 위장"이 재발하기 때문(None=미가용 / []=가용·0건 / raise=실행 실패 3분기)."""
    backend = resolve_backend(mem_cfg)
    if backend is None:
        return None
    # limit 정수 강제 + 범위 clamp(적대 리뷰 104 P2). 엔드포인트는 스키마(1-10)로 막지만 브로커 위임
    # 경로는 args의 limit을 검증 없이 넘겨(`{"limit":"boom"}`) `[:limit]`에서 TypeError·`-1`로 꼬리절단
    # 될 수 있었다. 여기(084가 이미 방어 슬라이스를 둔 지점)서 한 번 정규화해 세 입구를 같은 경계로.
    n = _clamp_limit(limit)
    return backend.search(scope, query, n)[:n]


# 예외/텍스트에서 비밀로 보이는 토큰 마스킹(스펙 125) — 진단 error 문자열이 비밀을 흘리지 않게.
# **1차 방어는 mem_cfg의 실제 api_key 값을 정확 치환**(정규식 추측이 아니라 — 어떤 형태든 확실히 제거).
# 2차 백스톱 정규식: sk-/Bearer + 라벨(api_key·authorization·token·secret·password) 뒤 값. base_url·
# model_id는 비밀 아님(그대로). 라벨 뒤 값은 공백/따옴표/`:`/`=` 뒤 형태를 넓게 잡는다(codex 125 H1).
_SECRET_RE = _re.compile(
    r"(sk-[A-Za-z0-9_\-]{6,}"
    r"|Bearer\s+[A-Za-z0-9._\-+/]{6,}"
    r"|(?:api[_-]?key|authorization|auth[_-]?token|access[_-]?token|token|secret|password)"
    r"['\"]?\s*[:=]\s*['\"]?(?:Bearer\s+)?[A-Za-z0-9._\-+/]{6,})",
    _re.I,
)


def _sanitize(text: object, *, secrets: object = (), cap: int = 300) -> str:
    """진단 노출용 문자열 정제 — 비밀 마스킹 + 길이 상한. 항상 str 반환.

    secrets: mem_cfg에서 뽑은 실제 비밀 값(api_key 등). **정확 치환이 1차 방어**(형태 무관 확실 제거).
    이후 정규식 백스톱으로 라벨/토큰 형태를 추가로 마스킹. 짧은/빈 secret은 오탐 방지로 건너뛴다."""
    s = str(text)
    for sec in secrets or ():
        if isinstance(sec, str) and len(sec) >= 4:
            s = s.replace(sec, "«secret»")
    s = _SECRET_RE.sub("«secret»", s)
    return s[:cap] + ("…" if len(s) > cap else "")


def _cfg_secrets(mem_cfg: object) -> list[str]:
    """mem_cfg의 llm·embedder api_key(있으면) — _sanitize 정확 치환용. 비밀 외 필드는 미포함."""
    out: list[str] = []
    if isinstance(mem_cfg, dict):
        for sect in (mem_cfg.get("llm"), mem_cfg.get("embedder")):
            if isinstance(sect, dict) and isinstance(sect.get("api_key"), str):
                out.append(sect["api_key"])
    return out


def _model_id(section: object) -> str | None:
    """mem_cfg의 llm/embedder 섹션에서 model_id만(비밀 아님). dict 아니면 None."""
    return section.get("model_id") if isinstance(section, dict) else None


def recall_diag(scope: dict, query: str, mem_cfg: dict | None, limit: int = 4) -> dict:
    """회상 *진단*(스펙 125) — `recall_probe`가 모든 미가용을 None으로 뭉개고 검색 예외를 던지는 대신,
    **왜 안 되는지**를 구조화해 돌린다(예외를 던지지 않음). 반환:
      {configured, backend_ready, embedder_model, llm_model, error, results}
    - configured: mem_cfg에 llm·embedder 둘 다. - backend_ready: resolve_backend 비-None.
    - error: 미설정/초기화 실패/검색 예외를 사람이 읽는(비밀 마스킹) 문자열로. 정상이면 None.
    회상 코어(`search`)는 무변경 — 이건 시험 도구 전용 추가(drift 0). 비밀(api_key)은 절대 미포함."""
    llm = mem_cfg.get("llm") if isinstance(mem_cfg, dict) else None
    emb = mem_cfg.get("embedder") if isinstance(mem_cfg, dict) else None
    configured = bool(llm and emb)
    secrets = _cfg_secrets(mem_cfg)  # 실제 api_key 정확 치환용(codex 125 H1)
    diag: dict = {
        "configured": configured,
        "backend_ready": False,
        "embedder_model": _model_id(emb),
        "llm_model": _model_id(llm),
        "error": None,
        "results": [],
        "stored": None,  # 스코프 저장 건수(스펙 158) — 저장>0인데 회상 0이면 유사도/임베더 문제 신호
    }
    # resolve_backend가 **가용성의 단일 권위**(recall_probe와 동일 경로 — configured로 조기반환하면
    # resolve_backend를 우회해 계약이 갈린다). 항상 호출하고, configured는 error *문구 선택*에만 쓴다.
    try:
        backend = resolve_backend(mem_cfg)
    except Exception as exc:  # noqa: BLE001 — 진단은 모든 예외를 삼켜 구조화(던지지 않음)
        diag["error"] = "메모리 백엔드 초기화 실패: " + _sanitize(exc, secrets=secrets)
        return diag
    if backend is None:
        # 미가용 사유를 configured로 갈라 명시: 모델 미설정 vs (설정됐으나) 초기화 실패.
        diag["error"] = (
            "임베딩/LLM 모델이 설정되지 않았습니다 (에이전트 메모리·모델 설정을 확인하세요)."
            if not configured
            else "메모리 백엔드 초기화에 실패했습니다 (임베딩/LLM 모델 접속·설정을 확인하세요)."
        )
        return diag
    diag["backend_ready"] = True
    # 스코프 저장 건수(스펙 158) — count(*)로 싸게(list_all은 최대 1만행 페치라 금지). 저장>0인데 회상 0이면
    # 유사도<임계·임베더/벡터공간 문제 신호. 카운트 실패는 진단을 막지 않음(None 유지).
    try:
        diag["stored"] = int(backend.list_page(scope, None, 1, 0).get("total", 0))
    except Exception:  # noqa: BLE001 — 카운트는 보조 신호(실패해도 회상 진단 진행)
        diag["stored"] = None
    try:
        n = _clamp_limit(limit)
        # threshold=0.0(스펙 158): UI 약속("관련도 내림차순 상위 기억")대로 top-k를 점수 무관 표시한다.
        # mem0의 숨은 기본 0.1이 저유사도(arctic query-prefix 미주입·약한 질의 등)를 전부 컷해 "정상·0건"
        # 위장을 만들던 것을 종료 — 낮은 점수까지 보여 사용자가 원인(임베더/질의 유사도)을 자가진단.
        diag["results"] = backend.search(scope, query, n, threshold=0.0)[:n]
    except Exception as exc:  # noqa: BLE001 — 전 축 실패(임베더 호출 등)를 500 대신 진단 error로(M1 표면화)
        diag["error"] = "검색 실행 실패: " + _sanitize(exc, secrets=secrets)
        return diag
    # 정직한 0건 진단(스펙 158): 예외는 없는데 저장>0·회상0이면 유사도/필터/벡터공간 심층 문제.
    if not diag["results"] and diag["stored"]:
        diag["error"] = (
            f"스코프에 {diag['stored']}건이 저장돼 있으나 회상 0건입니다 — 질의-기억 유사도가 매우 낮거나"
            "(질의 어휘·임베더 query prefix 문제), 저장 시 임베더와 현재 임베더가 달라 벡터공간이"
            " 어긋났을 수 있습니다(다르면 재인덱싱 필요). 필터 축 불일치도 확인하세요."
        )
    return diag


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


def list_page(scope: dict, q: str | None, mem_cfg: dict | None, limit: int = 20, offset: int = 0) -> dict | None:
    """기억 페이지 목록(스펙 127) — {"items", "total"}. 백엔드 미가용(미구성) → None(빈 결과와 구분,
    recall_probe와 동일 계약). 백엔드 실패는 **던진다**(관리 조회 실패≠0건, learning 125) — 호출 라우트가
    오류로 표면화한다."""
    backend = resolve_backend(mem_cfg)
    if backend is None:
        return None
    return backend.list_page(scope, q, limit, offset)


def user_owns(user_id: str, mem_id: str, mem_cfg: dict | None) -> bool:
    """mem_id가 이 user_id의 기억에 속하는지(소유권 술어 — **단일 출처**, 스펙 111). 공유 pgvector라
    전역 mem_id를 소유자 스코프 목록과 대조하지 않으면 임의 user_id/agent_id 행을 id만으로 변조 가능
    (learning 054). HTTP 라우트(`_assert_user_owns`)와 브로커 memedit invoke가 이 술어를 공유한다
    (드리프트 0). 순수 판정 — 호출자가 `asyncio.to_thread`로 감싼다(list_memories가 동기 백엔드 I/O)."""
    return any(r["id"] == mem_id for r in list_memories({"user_id": user_id}, mem_cfg))


def update_memory(mem_id: str, text: str, mem_cfg: dict | None) -> bool:
    """기억 본문 수정. 성공 True / 실패·무력화 False. (스펙 029)"""
    backend = resolve_backend(mem_cfg)
    return backend.update(mem_id, text) if backend else False


def delete_memory(mem_id: str, mem_cfg: dict | None) -> bool:
    """기억 삭제. 성공 True / 실패·무력화 False. (스펙 029)"""
    backend = resolve_backend(mem_cfg)
    return backend.delete(mem_id) if backend else False
