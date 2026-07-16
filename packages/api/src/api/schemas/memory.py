"""schemas.memory — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

from pydantic import BaseModel, Field, field_validator

from .base import _require_non_blank


class MemorySearchIn(BaseModel):
    """메모리 회상 시험 입력(스펙 084) — 스코프(agent_id/user_id)에 질의를 던져 상위 기억을 받는다.

    `memory.search`는 챗에서 요청-바운드 `user_text`를 받지만, 직접 엔드포인트는 임의 입력이라
    입력 신뢰경계가 리셋된다(적대 리뷰 072 P2와 동형) — 거대 query가 mem0 임베딩을 점유하지 않게
    raw 길이서 캡하고, 공백 query는 422로 막는다."""

    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=4, ge=1, le=10)

    _non_blank = field_validator("query")(_require_non_blank)


class MemoryHit(BaseModel):
    # (스펙 324) type 필드 제거 — 항상 "semantic" 상수라 정보량 0이던 폐기 분류(의미/일화/절차)의 화석.
    text: str
    score: float  # 내림차순(1.0=가장 관련)
    scope: str  # 매치된 스코프 축 이름(agent_id/user_id/run_id)


class MemoryPageItem(BaseModel):
    """페이지 목록 항목(스펙 127) — created/updated는 mem0 payload의 ISO 문자열(없으면 None)."""

    id: str
    text: str
    created_at: str | None = None
    updated_at: str | None = None


class MemoryPageOut(BaseModel):
    """기억 페이지 목록(스펙 127) — 서버 페이지네이션 + 부분일치(q). enabled=False는 메모리 미구성
    (빈 결과와 구분, 084/125 정직성 계약). 백엔드 *실패*는 이 스키마가 아니라 502로 표면화(실패≠0건)."""

    items: list[MemoryPageItem]
    total: int  # q 적용 후 전체 건수
    limit: int
    offset: int
    enabled: bool


class MemorySearchDiag(BaseModel):
    """회상 시험 진단(스펙 125) — "왜 0건/실패인지"를 UI가 지속 표시. 비밀(api_key) 절대 미포함."""

    configured: bool  # mem_cfg에 llm·embedder 둘 다 있나
    backendReady: bool  # resolve_backend 비-None(초기화 성공)
    embedderModel: str | None = None  # embedder model_id(비밀 아님)
    llmModel: str | None = None
    error: str | None = None  # 미설정/초기화 실패/검색 예외(정제·마스킹). 정상이면 None
    scope: str  # 질의 스코프(user_id 등)
    count: int  # 회상 건수
    stored: int | None = (
        None  # 스코프 저장 건수(스펙 158) — 저장>0인데 회상 0이면 유사도/임베더 문제
    )


class MemorySearchOut(BaseModel):
    """메모리 회상 시험 결과 — production 회상 코어(`memory.search`)와 동일 경로 산출.

    `enabled=False`는 메모리 미구성/비활성(mem_cfg None) — "결과 없음(빈 results)"과 구분해
    UI가 정직하게 표시(스펙 079 '0건도 일어난 일'). 미구성은 502가 아니라 빈 결과로 graceful."""

    query: str
    limit: int
    enabled: bool
    results: list[MemoryHit]  # 회상 0건이면 빈 리스트
    diag: MemorySearchDiag | None = (
        None  # 진단(스펙 125) — 선택. 컬렉션 검색 등 비-메모리 경로는 None
    )
