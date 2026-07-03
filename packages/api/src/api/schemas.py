"""Pydantic 입출력 스키마 (007 도메인)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ORM = {"from_attributes": True}


# ----------------------------- 빌딩 블록 -----------------------------
class PersonaIn(BaseModel):
    name: str = Field(max_length=200)  # 식별 이름(규칙, 스펙 148) — DB String(200) 정합(codex 148)
    alias: str | None = Field(default=None, max_length=200)  # 별명(자유 표기, 스펙 148) — 표시 = alias ?? name
    tone: str | None = None
    body: str = ""


class PersonaOut(PersonaIn):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ORM


class MemoryTypeIn(BaseModel):
    key: str
    name: str
    scope: str | None = None
    body: str = ""


class MemoryTypeOut(MemoryTypeIn):
    id: uuid.UUID
    model_config = ORM


class CollectionIn(BaseModel):
    """컬렉션 생성 — 임베딩 모델 1개로 묶임. dims는 서버가 probe 실측으로 박제(클라이언트 미지정)."""

    name: str = Field(max_length=200)  # 식별 이름(규칙, 스펙 148) — DB String(200) 정합
    alias: str | None = Field(default=None, max_length=200)  # 별명(자유 표기, 스펙 148)
    kind: Literal["document", "entity"] = "document"  # 종류 축(스펙 149) — 생성 후 불변
    # 엔티티 행 검증 JSON Schema(선택, 스펙 149) — 서버가 check_schema로 스키마 자체 유효성 검증
    entity_schema: dict[str, Any] | None = None
    description: str = ""
    embedding_model_id: uuid.UUID
    chunk_size: int = Field(default=1000, gt=0)  # 0/음수면 1자 청크 폭주 — 422로 거부
    chunk_overlap: int = Field(default=200, ge=0)


class CollectionUpdate(BaseModel):
    """수정 — 임베딩 모델·dims는 생성 후 불변(차원 고정). 청킹 설정·설명·별명만 수정 가능
    (식별 이름은 참조 키라 v1 불변)."""

    alias: str | None = Field(default=None, max_length=200)  # 별명(스펙 148)
    description: str | None = None
    chunk_size: int | None = Field(default=None, gt=0)
    chunk_overlap: int | None = Field(default=None, ge=0)
    # 엔티티 스키마 갱신(스펙 149) — 이후 업로드부터 적용(기존 행 재검증 없음).
    # 필드 미포함=미변경, 명시적 null=제거(model_fields_set 판별 — 오등록 스키마 해제 경로, codex 149)
    entity_schema: dict[str, Any] | None = None


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    alias: str | None = None  # 별명(스펙 148)
    kind: str = "document"  # 종류 축(스펙 149)
    entity_schema: dict[str, Any] | None = None  # 엔티티 행 검증 스키마(스펙 149)
    description: str
    embedding_model_id: uuid.UUID
    embedding_model_name: str  # denormalized 표시용
    dims: int
    chunk_size: int
    chunk_overlap: int
    doc_count: int
    chunk_count: int
    status: str
    owner_id: str | None = None  # 소유자(스펙 112). None=공유/레거시
    can_manage: bool = True  # 이 요청 주체가 수정/삭제 가능(스펙 114, list/get서 계산·기본 True)


class DocumentOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    filename: str
    content_type: str | None = None
    byte_size: int
    chunk_count: int
    status: str
    error: str | None = None
    model_config = ORM


class DocumentPageOut(BaseModel):
    """문서 페이지 목록(스펙 128) — 문서는 증가 축이라 서버 페이지네이션(세션·메모리와 동형 패턴)."""

    items: list[DocumentOut]
    total: int  # q(파일명 부분일치) 적용 후 전체 건수


class CollectionHealth(BaseModel):
    """차원 정합 점검(읽기 전용) — DB 컬럼 / Collection 박제 / 현재 임베딩 모델 probe 3자 비교."""

    collection_id: uuid.UUID
    db_dims: int  # rag_chunks.embedding 컬럼 차원(RAG_EMBED_DIMS)
    collection_dims: int  # Collection.dims (생성 시 박제)
    model_dims: int | None = None  # 현재 임베딩 모델 probe 실측(None=probe 실패)
    consistent: bool
    detail: str = ""


class CollectionSearchIn(BaseModel):
    """retrieval 시험 입력(스펙 072) — 단일 컬렉션에 질의를 던져 상위 청크를 받는다."""

    # 빈/공백 질의는 422. max_length는 raw 상한(적대 리뷰 072 P2): 직접 POST라 LLM 입력 한계에
    # 못 기댄다 — 거대 query가 임베딩 provider를 60초 점유·메모리 폭주시키지 않게 입력서 캡한다.
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=4, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        # min_length는 strip 전 길이라 공백("   ")이 통과 → 코어서 빈값으로 502가 됐다.
        # 입력 경계에서 strip 후 비면 422로 거부(서버 오류 502가 아니라 잘못된 입력).
        s = v.strip()
        if not s:
            raise ValueError("질의는 공백일 수 없습니다.")
        return s


class SearchHit(BaseModel):
    score: float  # 1 - cosine_distance (1.0=동일 벡터). 내림차순.
    filename: str
    text: str
    meta: dict[str, Any] | None = None  # 엔티티 metadata(스펙 149) — 문서형 hit은 None


class CollectionSearchOut(BaseModel):
    """retrieval 시험 결과 — production 검색 코어(`search_collections`)와 동일 경로 산출."""

    query: str
    top_k: int
    results: list[SearchHit]  # 관련 0건이면 빈 리스트


class MemorySearchIn(BaseModel):
    """메모리 회상 시험 입력(스펙 084) — 스코프(agent_id/user_id)에 질의를 던져 상위 기억을 받는다.

    `memory.search`는 챗에서 요청-바운드 `user_text`를 받지만, 직접 엔드포인트는 임의 입력이라
    입력 신뢰경계가 리셋된다(적대 리뷰 072 P2와 동형) — 거대 query가 mem0 임베딩을 점유하지 않게
    raw 길이서 캡하고, 공백 query는 422로 막는다."""

    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=4, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("질의는 공백일 수 없습니다.")
        return s


class MemoryHit(BaseModel):
    type: str  # "semantic" 등 — 백엔드가 분류
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


class MemorySearchOut(BaseModel):
    """메모리 회상 시험 결과 — production 회상 코어(`memory.search`)와 동일 경로 산출.

    `enabled=False`는 메모리 미구성/비활성(mem_cfg None) — "결과 없음(빈 results)"과 구분해
    UI가 정직하게 표시(스펙 079 '0건도 일어난 일'). 미구성은 502가 아니라 빈 결과로 graceful."""

    query: str
    limit: int
    enabled: bool
    results: list[MemoryHit]  # 회상 0건이면 빈 리스트
    diag: MemorySearchDiag | None = None  # 진단(스펙 125) — 선택. 컬렉션 검색 등 비-메모리 경로는 None


class PermissionIn(BaseModel):
    name: str = Field(max_length=120)  # 식별 이름(규칙, 스펙 148) — DB String(120) 정합
    alias: str | None = Field(default=None, max_length=200)  # 별명(자유 표기, 스펙 148)
    scope: str | None = None
    approver: Literal["user", "admin"] = "user"
    body: str = ""


class PermissionOut(PermissionIn):
    id: uuid.UUID
    model_config = ORM


class McpToolParam(BaseModel):
    """도구 파라미터 요약(스펙 151) — args 스키마에서 파생한 표시용. 길이 캡=원격 유래 방어."""

    name: str = Field(max_length=80)
    type: str = Field(default="any", max_length=40)
    required: bool = False


class McpToolInfo(BaseModel):
    """도구 메타(스펙 151) — 탐색 시점 스냅샷. 캡은 _tool_info 파생값과 정합(설명500·파라미터30)."""

    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=500)
    params: list[McpToolParam] = Field(default_factory=list, max_length=30)


class McpServerIn(BaseModel):
    name: str = Field(max_length=120)  # 식별 이름(규칙, 스펙 148) — DB String(120) 정합
    alias: str | None = Field(default=None, max_length=200)  # 별명(자유 표기, 스펙 148)
    source: Literal["local", "external"] = "local"
    transport: Literal["stdio", "http"] = "stdio"
    url: str | None = None
    endpoint: str | None = None
    tools: list[str] = Field(default_factory=list)
    enabled_tools: list[str] = Field(default_factory=list)
    # 도구 메타 스냅샷(스펙 151) — name→{description, params}. None=미변경(편집 시 기존 보존)
    tools_meta: dict[str, Any] | None = None
    status: str = "connected"
    published: bool = False
    auth: str | None = None

    @field_validator("tools_meta")
    @classmethod
    def _check_tools_meta(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """직접 저장 경로 방어(codex 151 High) — discover 경유 캡이 직접 POST/PUT엔 안 걸리므로
        입력 경계에서 구조·크기를 강제(서버당 100개·McpToolInfo 캡). 위반=422, 정규화해 반환."""
        if v is None:
            return v
        if not isinstance(v, dict) or len(v) > 100:
            raise ValueError("tools_meta는 도구 100개 이하의 객체여야 합니다.")
        out: dict[str, Any] = {}
        for k, item in v.items():
            if not isinstance(k, str) or not isinstance(item, dict):
                raise ValueError("tools_meta 항목은 {도구이름: {description, params}} 형식이어야 합니다.")
            try:
                info = McpToolInfo(
                    name=k,
                    description=item.get("description", "") or "",
                    params=item.get("params", []) or [],
                )
            except Exception as exc:  # noqa: BLE001 — pydantic 상세를 422 메시지로
                raise ValueError(f"tools_meta[{k[:40]!r}] 형식 위반: {str(exc)[:200]}")
            out[info.name] = {
                "description": info.description,
                "params": [p.model_dump() for p in info.params],
            }
        return out


class McpServerOut(McpServerIn):
    id: uuid.UUID
    owner_id: str | None = None  # 소유자(스펙 112). None=공유/레거시
    can_manage: bool = True  # 요청 주체 수정/삭제 가능(스펙 114, list/get서 계산·기본 True)
    model_config = ORM


class McpPublishIn(BaseModel):
    published: bool


class McpDiscoverIn(BaseModel):
    """MCP 서버 라이브 도구 탐색(저장 전 폼). url에 실제로 붙어 도구목록만 읽는다(부작용 0, 스펙 054 E)."""
    url: str = ""
    transport: Literal["stdio", "http"] = "http"
    auth: str | None = None  # 평문 토큰(폼 입력) 또는 마스킹값(• 포함이면 헤더 생략)


class McpDiscoverResult(BaseModel):
    """탐색 결과. ok=연결+도구취득 성공. tools=발견된 도구이름. 비밀은 결과에 미포함."""
    ok: bool
    reachable: bool
    tools: list[str] = Field(default_factory=list)
    toolsDetail: list[McpToolInfo] = Field(default_factory=list)  # 도구 메타(스펙 151)
    latencyMs: int = 0
    detail: str = ""


class ProviderProbeIn(BaseModel):
    """provider 연결 테스트(저장 전 폼). base_url 도달성 + 자격증명 확인."""
    base_url: str = ""
    api_key: str | None = None


class ModelProbeIn(BaseModel):
    """모델 연결 테스트(저장 전 폼). 연결처는 선택한 provider에서 취득."""
    provider_id: uuid.UUID
    model_id: str = ""
    kind: Literal["chat", "embedding"] = "chat"


class ModelProbeResult(BaseModel):
    ok: bool  # 도달 + 인증 성공
    reachable: bool
    modelAvailable: bool  # 기능 검증 통과 (chat: 목록 존재 / embedding: 임베딩 호출 성공)
    latencyMs: int
    detail: str = ""  # 상태/일반 메시지 (비밀 미포함)
    dims: int | None = None  # 임베딩 벡터 차원 (kind=embedding 성공 시)


# ----------------------------- Provider 레지스트리 (035) -----------------------------
class ProviderIn(BaseModel):
    name: str
    protocol: str = "openai-compatible"
    base_url: str = ""
    api_key: str | None = None
    kind: Literal["local", "mock", "remote"] = "remote"  # 표시·배지(스펙 047 #6)
    description: str = ""


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    protocol: str
    base_url: str
    api_key: str | None = None  # 마스킹되어 내려옴
    kind: str = "remote"  # local|mock|remote
    description: str = ""
    modelCount: int = 0  # 매달린 모델 수(삭제 차단 안내·표시용)


# ----------------------------- 모델 레지스트리 -----------------------------
class ModelIn(BaseModel):
    name: str
    provider_id: uuid.UUID  # 연결처는 provider에서 상속
    model_id: str = ""
    kind: Literal["chat", "embedding"] = "chat"
    is_default: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)  # models.dev 카탈로그 메타(스펙 047 #7)


class ModelOut(BaseModel):
    id: uuid.UUID
    name: str
    provider_id: uuid.UUID
    provider_name: str  # 표시용(denormalized)
    base_url: str  # provider에서 상속(표시용)
    model_id: str
    kind: str
    is_default: bool
    params: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)  # 카탈로그 파생(context·modalities·cost·caps)


# 통합 뷰의 GET /models 실모델 나열·토글용(스펙 047 #8).
class AvailableModel(BaseModel):
    model_id: str  # 프로바이더가 돌려준 raw id
    registered: bool  # 이 프로바이더+model_id로 ModelConfig가 이미 존재하나
    registered_name: str | None = None  # 등록돼 있으면 그 표시 이름
    registered_id: uuid.UUID | None = None  # 등록돼 있으면 ModelConfig.id(토글 OFF용)
    catalog: dict[str, Any] | None = None  # models.dev 매칭 메타(없으면 None)


class AvailableModelsOut(BaseModel):
    reachable: bool  # base_url GET /models 도달 여부
    detail: str = ""  # 도달 실패 시 안내(비밀 미포함)
    models: list[AvailableModel] = Field(default_factory=list)


# ----------------------------- 에이전트 -----------------------------
class AgentConfig(BaseModel):
    model: str = "mock-llm"  # 미지정 시 기본 모델(스펙 059)
    persona: str = ""  # 페르소나 이름(블록 참조)
    temperature: float | None = None  # 에이전트 영속 온도(스펙 077). None=자동(모델 등록 params 적용)
    memories: list[str] = Field(default_factory=list)
    vectorTables: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    # 능력 브로커 allowlist(스펙 100 §69·101) — 오케스트레이터가 서브스텝 위임할 수 있는 능력 id.
    # 규약: bare=agent cap, `mcp:<server>`=서버 전체, `mcp:<server>/<tool>`=툴 단위. 없으면 []=deny-by-
    # default. 실제 인가는 요청 시 RBAC와 교집합(build_broker). UI 편집은 Phase 2-d로 이연(스펙 101).
    capabilities: list[str] = Field(default_factory=list)
    historyDepth: int = 20
    persistHistory: bool = True  # 대화를 DB에 저장할지(끄면 윈도우 모드)
    # A2A 위임 승인 opt-in(스펙 117) — 이 에이전트에게 위임(A2A 전송)할 때 승인 게이트를 걸지. 기본 False=
    # 게이트 없음(무회귀). 브로커 AgentProvider.approval_for가 read하는 정책 소스라 **라운드트립 보존 필수**
    # (없으면 model_dump가 조용히 드롭 → 게이트 비활성, learning 101 seed-bypasses-write-schema).
    requires_approval: bool = False
    impl: str | None = None  # in-process 커스텀 런타임 키(스펙 085). None=기본 DefaultUiAgent.
    # 신뢰 레지스트리의 *키*일 뿐 코드 아님 — 미지/미등록 키는 조용히 기본으로 폴백(eval 없음).


class AgentCreate(BaseModel):
    name: str = Field(max_length=200)  # 식별 이름(규칙, 스펙 148) — DB String(200) 정합
    alias: str | None = Field(default=None, max_length=200)  # 별명(자유 표기, 스펙 148)
    config: AgentConfig = Field(default_factory=AgentConfig)


class AgentUpdate(BaseModel):
    """편집 = 초안(draft) 버전에 저장."""

    name: str | None = Field(default=None, max_length=200)  # 식별 이름(규칙, 스펙 148)
    alias: str | None = Field(default=None, max_length=200)  # 별명(자유 표기, 스펙 148) — None=미변경("" = 비우기)
    config: AgentConfig


class VersionOut(BaseModel):
    version: str
    status: str
    note: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None


class AgentOut(BaseModel):
    id: uuid.UUID
    agentId: str
    name: str  # 식별 이름(규칙, 스펙 148)
    alias: str | None = None  # 별명(자유 표기, 스펙 148) — 표시 = alias ?? name
    source: str
    model: str
    persona: str  # 페르소나 이름(블록 참조, UI 표시용)
    temperature: float | None = None  # 에이전트 영속 온도(스펙 077). None=자동(모델 등록값)
    systemPrompt: str = ""  # 해석된 시스템 프롬프트 본문(런타임이 쓰는 것)
    historyDepth: int
    persistHistory: bool = True
    impl: str | None = None  # in-process 커스텀 런타임 키(스펙 085) — 폼 재로드/라운드트립 보존용
    # 공통 인터페이스 준수 분류(스펙 089) — 파생값(저장 안 함). conforming=준수(default/적합 impl),
    # non_conforming=A2A 원격(정당한 다른 종류), config_error=impl 선언했으나 미해결(설정 실패).
    conformance: str = "conforming"
    memories: list[str] = Field(default_factory=list)
    vectorTables: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)  # 능력 브로커 allowlist(스펙 106, 폼 재로드용)
    owner_id: str | None = None  # 소유자(스펙 112). None=공유/레거시
    can_manage: bool = True  # 요청 주체 수정/삭제 가능(스펙 114, list/get서 계산·기본 True)
    exposed: dict[str, Any] = Field(default_factory=lambda: {"a2a": False})
    status: str
    activeVersion: str | None = None
    versions: list[VersionOut] = Field(default_factory=list)
    # code agent meta
    endpoint: str | None = None
    token: str | None = None
    runtime: str | None = None
    repo: str | None = None
    commit: str | None = None
    registeredAt: str | None = None
    lastSync: str | None = None
    # external agent meta (source == "external") — 등록 시점 A2A Agent Card 스냅샷(읽기 전용)
    card: dict[str, Any] | None = None


class ExposeIn(BaseModel):
    a2a: bool


class ActivateIn(BaseModel):
    version: str


class ConnectAgentIn(BaseModel):
    """원격 에이전트 연결 — URL 하나로 A2A 카드를 fetch해 provenance 자동분류(스펙 057).

    백엔드가 카드의 my-agents 확장 유무로 source(code=우리가 배포한 SDK / external=제3자)를
    자동판별한다. 프론트는 매니페스트를 보내지 않는다(날조 제거). 등록 진입점 단일화."""

    url: str
    token: str | None = None  # 원격 호출 크레덴셜(있으면 crypto.encrypt 저장). 카드가 인증 불요면 None.


class RegisterExternalAgentIn(BaseModel):
    """외부 A2A 에이전트 등록 — 카드 URL만 받아 fetch·검증 후 등록(026, 1차). 057 이후 deprecated(connect로 대체)."""

    cardUrl: str
    token: str | None = None  # 외부 호출 크레덴셜(있으면 crypto.encrypt 저장). 카드가 인증 불요면 None.


class RegisterCodeAgentIn(BaseModel):
    endpoint: str
    token: str
    name: str | None = None
    model: str = "claude-sonnet-4"
    persona: str = "코드 정의 (SDK)"
    runtime: str | None = None
    repo: str | None = None
    commit: str | None = None
    memories: list[str] = Field(default_factory=list)
    historyDepth: int = 10
    permissions: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)


# ----------------------------- 세션/승인 -----------------------------
class SessionOut(BaseModel):
    id: str  # session_id (sess_...)
    agentId: str
    agent: str
    channel: str
    status: str
    turns: int
    tokens: int
    started: str | None = None
    lastActivity: str | None = None
    preview: str | None = None  # 첫 사용자 메시지 일부 — 사람이 알아볼 세션 라벨(스펙 055)


class SessionPage(BaseModel):
    """세션 목록 페이지 엔벌로프 (스펙 034)."""

    items: list[SessionOut]
    total: int  # 현재 필터 적용 총 건수 (페이지네이터용)
    counts: dict[str, int]  # 배지용 전체 집계, 키 all|live|awaiting|error (필터 무관)


class MessageOut(BaseModel):
    role: str
    content: str
    trace: dict[str, Any] | None = None


class ApprovalOut(BaseModel):
    id: str  # approval_id
    sessionId: str | None = None
    agentId: str | None = None
    agent: str
    permission: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str
    checkpoint: str | None = None
    status: str
    requestedAt: str | None = None


class ResolveIn(BaseModel):
    decision: Literal["approve", "reject"]


# ----------------------------- 채팅 -----------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    sessionId: str | None = None  # 이어서 대화할 세션(없으면 새로 생성)
    # mem0 user_id 축은 더는 클라이언트가 보내지 않는다(스펙 032). chat 핸들러가 인증 주체
    # (current_principal)에서 도출한다: 쿠키 유저면 str(user.id)(UUID), 머신 토큰이면 None(세션 단기).
    # Playground "Proxy" 세션 한정 오버라이드(스펙 025). **web 에이전트에만** 적용, 화이트리스트
    # 키만 의미(model/temperature/systemPrompt/mcps/memories/historyDepth). 저장된 에이전트는 불변.
    # 코드 에이전트는 원격 실행이라 무시(bypass).
    overrides: dict | None = None


# ----------------------------- 인증·권한 (스펙 031) -----------------------------
# fastapi-users Pydantic 스키마. BaseUser는 id/email/is_active/is_superuser/is_verified 포함.
from fastapi_users import schemas as _fu_schemas  # noqa: E402


class UserRead(_fu_schemas.BaseUser[uuid.UUID]):
    source: str
    display_name: str | None = None


class UserCreate(_fu_schemas.BaseUserCreate):
    display_name: str | None = None


class UserUpdate(_fu_schemas.BaseUserUpdate):
    display_name: str | None = None


class RoleAssignIn(BaseModel):
    role: str


class RoleOut(BaseModel):
    name: str
    description: str = ""
    model_config = ORM


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    source: str
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    model_config = ORM
