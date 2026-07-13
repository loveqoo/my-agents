"""Pydantic 입출력 스키마 (007 도메인)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ORM = ConfigDict(from_attributes=True)


def _require_non_blank(v: str) -> str:
    """검색 질의 공백 거부(스펙 296 정본) — min_length는 strip 전 길이라 공백("   ")이 통과해
    코어서 빈값으로 502가 됐다. 입력 경계서 strip 후 비면 422로 거부(서버 오류가 아니라 잘못된 입력)."""
    s = v.strip()
    if not s:
        raise ValueError("질의는 공백일 수 없습니다.")
    return s


# ----------------------------- 빌딩 블록 -----------------------------
class PersonaIn(BaseModel):
    name: str = Field(max_length=200)  # 식별 이름(규칙, 스펙 148) — DB String(200) 정합(codex 148)
    description: str | None = Field(
        default=None, max_length=200
    )  # 설명(자유 표기, 스펙 210) — 표시는 name 단독
    tone: str | None = None
    body: str = ""


class PersonaOut(PersonaIn):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ORM


class PersonaUsageAgentOut(BaseModel):
    """페르소나를 쓰는 에이전트 1건(스펙 161) — 편집 화면 "사용 에이전트·오래됨" 목록용."""

    id: uuid.UUID
    agentId: str
    name: str
    description: str | None = None
    stale: bool  # 이 에이전트 스냅샷이 현재 페르소나 본문과 다름
    canManage: bool  # 요청 주체가 이 에이전트를 갱신할 수 있음(스펙 112/114)


class PersonaApplyIn(BaseModel):
    agentIds: list[uuid.UUID]  # 이 페르소나 최신 본문을 반영할 에이전트들


class PersonaApplyOut(BaseModel):
    applied: list[uuid.UUID]  # 실제 갱신된 에이전트
    skipped: list[uuid.UUID]  # 관리 불가/미참조로 건너뜀


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
    kind: Literal["document", "entity"] = "document"  # 종류 축(스펙 149) — 생성 후 불변
    # 엔티티 행 검증 JSON Schema(선택, 스펙 149) — 서버가 check_schema로 스키마 자체 유효성 검증
    entity_schema: dict[str, Any] | None = None
    description: str = ""
    embedding_model_id: uuid.UUID
    chunk_size: int = Field(default=1000, gt=0)  # 0/음수면 1자 청크 폭주 — 422로 거부
    chunk_overlap: int = Field(default=200, ge=0)


class CollectionUpdate(BaseModel):
    """수정 — 임베딩 모델·dims·**청크 정책**은 생성 후 불변(스펙 198: 청크 수정은 기존 문서에 소급 안 되고
    재청킹은 원본 미저장이라 불가 → 혼란 방지 위해 수정 자체 제거). 설명만 수정 가능
    (식별 이름은 참조 키라 v1 불변)."""

    description: str | None = None
    # 엔티티 스키마 갱신(스펙 149) — 이후 업로드부터 적용(기존 행 재검증 없음).
    # 필드 미포함=미변경, 명시적 null=제거(model_fields_set 판별 — 오등록 스키마 해제 경로, codex 149)
    entity_schema: dict[str, Any] | None = None


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
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


class ReindexIn(BaseModel):
    """재인덱싱 요청(스펙 312) — 준 필드만 변경(부분). 최소 하나는 현재와 달라야 no-op이 아니다.

    embedding_model_id: 임베딩 모델 교체(같은 차원 1024만). chunk_size/overlap: 재청킹(문서형만 —
    엔티티는 1행=1청크라 무의미). 청크 변경은 원본 blob이 있는 문서만 가능."""

    embedding_model_id: uuid.UUID | None = None
    chunk_size: int | None = Field(default=None, gt=0)
    chunk_overlap: int | None = Field(default=None, ge=0)


class ReindexEventOut(BaseModel):
    """재인덱싱 이력 1건(스펙 312) — 컬렉션의 모델·청크 정책 계보."""

    id: uuid.UUID
    collection_id: uuid.UUID
    from_model_name: str | None = None
    to_model_name: str | None = None
    from_chunk_size: int | None = None
    from_chunk_overlap: int | None = None
    to_chunk_size: int | None = None
    to_chunk_overlap: int | None = None
    chunk_count: int
    status: str
    error: str | None = None
    owner_id: str | None = None
    created_at: datetime


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

    _non_blank = field_validator("query")(_require_non_blank)


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

    _non_blank = field_validator("query")(_require_non_blank)


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
    description: str | None = Field(
        default=None, max_length=200
    )  # 설명(자유 표기, 스펙 210) — 표시는 name 단독
    # local=외부/self-host 등록분 · external=남의 A2A/MCP(재공개 봉인 152) · custom=우리가 코드로
    # 정의·호스팅해 서빙 가능(스펙 156). source는 생성 후 불변(152) — 세탁 봉인.
    source: Literal["local", "external", "custom"] = "local"
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
                raise ValueError(
                    "tools_meta 항목은 {도구이름: {description, params}} 형식이어야 합니다."
                )
            try:
                info = McpToolInfo(
                    name=k,
                    description=item.get("description", "") or "",
                    params=item.get("params", []) or [],
                )
            except Exception as exc:
                raise ValueError(f"tools_meta[{k[:40]!r}] 형식 위반: {str(exc)[:200]}") from exc
            entry: dict[str, Any] = {
                "description": info.description,
                "params": [p.model_dump() for p in info.params],
            }
            # 도구 승인 정책(스펙 177 P1) — 관리자가 도구별로 "승인 필요"를 데이터로 설정.
            # required=true만 정규화 보존(그 외 폐기). 승인자(approver)는 P2에서 추가.
            appr = item.get("approval")
            if isinstance(appr, dict) and bool(appr.get("required")):
                entry["approval"] = {"required": True}
            out[info.name] = entry
        return out


class McpServerOut(McpServerIn):
    id: uuid.UUID
    owner_id: str | None = None  # 소유자(스펙 112). None=공유/레거시
    can_manage: bool = True  # 요청 주체 수정/삭제 가능(스펙 114, list/get서 계산·기본 True)
    # 서빙 URL(스펙 156) — source=custom이고 레지스트리에 정의가 있을 때만. 외부가 이 URL로 등록·접속.
    # published=False면 아직 서빙 안 되지만(404) UI가 "공개하면 여기로 서빙" 안내에 쓴다. 그 외 None.
    served_url: str | None = None
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
    provider_kind: str = ""  # provider.kind(local|mock|remote) — mock 필터 등에 사용(스펙 218)
    base_url: str  # provider에서 상속(표시용)
    model_id: str
    kind: str
    is_default: bool
    params: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(
        default_factory=dict
    )  # 카탈로그 파생(context·modalities·cost·caps)


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
    temperature: float | None = (
        None  # 에이전트 영속 온도(스펙 077). None=자동(모델 등록 params 적용)
    )
    memories: list[str] = Field(default_factory=list)
    vectorTables: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    # 직접형 도구 단위 배선(스펙 276) — 런타임명(`server__tool`) 목록. **mcps(서버 목록)가 서버 배선의
    # 진실원**이고 tools는 그 위의 노출 필터: 서버별로 이 목록에 항목이 있으면 그 도구만, 없으면 전체
    # (구저장 빈 목록=지금과 동일=무회귀). model_dump 드롭 방지 위해 스키마 필드 필수(learning 101 동형).
    tools: list[str] = Field(default_factory=list)
    # 능력 브로커 allowlist(스펙 100 §69·101) — 오케스트레이터가 서브스텝 위임할 수 있는 능력 id.
    # 규약: bare=agent cap, `mcp:<server>`=서버 전체, `mcp:<server>/<tool>`=툴 단위. 없으면 []=deny-by-
    # default. 실제 인가는 요청 시 RBAC와 교집합(build_broker). UI 편집은 Phase 2-d로 이연(스펙 101).
    capabilities: list[str] = Field(default_factory=list)
    # 도구 승인 오버라이드(스펙 177 P2) — cap_id(`mcp:{server}/{tool}`)→{approval:{required?, approver?}}.
    # 도구 기본 정책(tools_meta)을 에이전트별로 강화(끔→켬)·완화(켬→끔)·승인자 변경. 리졸버가 덮어씀
    # (runtime.resolve_tool_approval). **완화는 저장 시 admin 게이트**(agents CRUD) — 스키마는 구조만 강제.
    toolPolicy: dict[str, Any] = Field(default_factory=dict)
    historyDepth: int = 20
    persistHistory: bool = (
        True  # 대화를 DB에 저장할지(끄면 윈도우 모드 — 세션은 남고 메시지만 스킵)
    )
    # 비영속(1회성) 모드(스펙 235) — true면 DB 적재 전면 스킵(세션 행·카운터·메시지·commit·메모리 전부
    # 무동작). 고트래픽·기록 무의미한 단순 추론 제공용. persistHistory의 상위집합. model_dump 드롭 방지 위해
    # 반드시 스키마 필드로 둔다(위 requires_approval 주석의 seed-bypasses-write-schema 함정과 동일).
    ephemeral: bool = False
    # 플레이그라운드 추천 명령어(스펙 238, 옵셔널) — 에이전트별 프롬프트 카드. 캡=최대 8개·각 200자
    # (직접 POST 입력 신뢰경계 — learning 075). 빈/공백 항목은 검증기가 걸러낸다.
    suggestedPrompts: list[str] = Field(default_factory=list)

    @field_validator("suggestedPrompts")
    @classmethod
    def _cap_suggested(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if isinstance(s, str) and s.strip()]
        if len(cleaned) > 8:
            raise ValueError("추천 명령어는 최대 8개까지입니다.")
        if any(len(s) > 200 for s in cleaned):
            raise ValueError("추천 명령어는 각 200자 이내여야 합니다.")
        return cleaned

    # A2A 위임 승인 opt-in(스펙 117) — 이 에이전트에게 위임(A2A 전송)할 때 승인 게이트를 걸지. 기본 False=
    # 게이트 없음(무회귀). 브로커 AgentProvider.approval_for가 read하는 정책 소스라 **라운드트립 보존 필수**
    # (없으면 model_dump가 조용히 드롭 → 게이트 비활성, learning 101 seed-bypasses-write-schema).
    requires_approval: bool = False
    impl: str | None = None  # in-process 커스텀 런타임 키(스펙 085). None=기본 DefaultUiAgent.
    # 신뢰 레지스트리의 *키*일 뿐 코드 아님 — 미지/미등록 키는 조용히 기본으로 폴백(eval 없음).
    # 노코드 산출물형(스펙 190) — {kind?, fields:[{key,label?,candidates?,required?}]}. impl=artifact_form이
    # 이 명세를 읽어 폼을 돈다(chat.py가 impl_config로 주입). 라운드트립 보존 필수(model_dump가 드롭하면
    # 폼 재로드 시 명세 소실 — learning 101 seed-bypasses-write-schema 동형).
    artifactSpec: dict[str, Any] | None = None
    # 노드형(스펙 259) — 일렬 파이프라인 노드 명세 [{name?, prompt, model?, tools?:[str]}]. impl=pipeline이
    # 이 리스트를 읽어 순서대로 실행(chat.py가 노드별 모델 해석 후 impl_config로 주입). 라운드트립 보존 필수.
    nodes: list[dict[str, Any]] | None = None
    # 컬렉션별 문서 검색 최소 유사도(스펙 191 v2) — {컬렉션명: 0~1}. 미만 문서는 검색 코어가 드롭.
    # 항목 없으면 그 컬렉션은 무필터. 값 0~1(1=완전 일치).
    ragMinScores: dict[str, float] = Field(default_factory=dict)

    @field_validator("ragMinScores", mode="before")
    @classmethod
    def _check_rag_min_scores(cls, v: Any) -> dict:
        """컬렉션별 임계값 맵 형태 검증(스펙 191 v2) — dict[str, 0~1]. 각 값 범위 밖·비수치면 거부.
        mode=before: bool(True→1.0)·문자열 코어싱 전 원값을 잡아 거부(숫자만 허용). 0 값은 허용(무필터)."""
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("ragMinScores는 객체여야 합니다.")
        out: dict[str, float] = {}
        for k, val in v.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError("ragMinScores 키(컬렉션명)는 비어있지 않은 문자열이어야 합니다.")
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(f"ragMinScores['{k}']는 숫자여야 합니다.")
            if not (0.0 <= float(val) <= 1.0):
                raise ValueError(f"ragMinScores['{k}']는 0.0~1.0 범위여야 합니다.")
            out[k] = float(val)
        return out

    @field_validator("artifactSpec")
    @classmethod
    def _check_artifact_spec(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """산출물 필드 명세 얕은 검증(스펙 190) — fields=배열·각 항목 문자열 key 필수(≤100개).
        의미 검증(후보 유효성 등)은 런타임 normalize_artifact_fields가 방어(빈/문자열후보 무시)."""
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("artifactSpec은 객체여야 합니다.")
        fields = v.get("fields")
        if fields is not None:
            if not isinstance(fields, list):
                raise ValueError("artifactSpec.fields는 배열이어야 합니다.")
            if len(fields) > 100:
                raise ValueError("artifactSpec.fields는 100개 이하여야 합니다.")
            for field in fields:
                if (
                    not isinstance(field, dict)
                    or not isinstance(field.get("key"), str)
                    or not field["key"].strip()
                ):
                    raise ValueError(
                        "artifactSpec.fields 항목은 비어있지 않은 문자열 key가 필요합니다."
                    )
        return v

    @staticmethod
    def _apply_node_scalar_fields(n: dict[str, Any], node: dict[str, Any]) -> None:
        """선택 스칼라 필드(name/model 길이 캡, 화이트리스트 enum, historyDepth 캡)를 node에 채운다."""
        for key in ("name", "model"):  # 문자열 필드(선택) — 길이 캡
            val = n.get(key)
            if isinstance(val, str) and val.strip():
                if len(val) > 200:
                    raise ValueError(f"nodes 항목 {key}은 200자 이하여야 합니다.")
                node[key] = val
        ctx_mode = n.get("context")  # 맥락 모드(스펙 260) — 화이트리스트 값만
        if ctx_mode in ("carry", "clean"):
            node["context"] = ctx_mode
        fmt = n.get("format")  # 출력 형식(스펙 261) — 화이트리스트 값만
        if fmt in ("text", "json"):
            node["format"] = fmt
        mem_q = n.get("memoryQuery")  # 회상 키워드 모드(스펙 268 P2) — 화이트리스트 값만
        if mem_q in ("user", "input"):
            node["memoryQuery"] = mem_q
        hd = n.get("historyDepth")  # 노드별 단기 기억 창(스펙 270) — 미지정=에이전트 상속.
        if isinstance(hd, int) and not isinstance(hd, bool):  # bool은 int 하위형 — 배제
            if hd > 1000:
                raise ValueError("nodes 항목 historyDepth는 1000 이하여야 합니다.")
            node["historyDepth"] = hd  # 음수·0 허용(음수/전체·0=대화 없음)

    @staticmethod
    def _apply_node_list_fields(n: dict[str, Any], node: dict[str, Any]) -> None:
        """선택 문자열 리스트 필드(tools/fields/memories, 개수·각 길이 캡)를 node에 채운다."""
        for key in ("tools", "fields", "memories"):
            lst = n.get(key)
            if isinstance(lst, list):
                if len(lst) > 100:
                    raise ValueError(f"nodes 항목 {key}은 100개 이하여야 합니다.")
                node[key] = [x for x in lst if isinstance(x, str) and len(x) <= 200]

    @staticmethod
    def _normalize_node_ref(n: dict[str, Any]) -> dict[str, Any]:
        """노드 라이브러리 참조 변형(스펙 316) — `{"ref": {"name", "version"}}`만 허용. 인라인 키와
        혼합 금지(참조와 직접 설정 중 어느 쪽이 진실인지 모호한 반쪽 저장 차단). version은 핀 고정
        (양의 정수 필수 — floating latest 없음). 존재 검증은 라우트가 DB로(assert_node_refs_exist)."""
        ref = n.get("ref")
        if (
            not isinstance(ref, dict)
            or not isinstance(ref.get("name"), str)
            or not ref["name"].strip()
        ):
            raise ValueError("nodes 참조 항목은 ref.name(비어있지 않은 문자열)이 필요합니다.")
        if len(ref["name"]) > 120:
            raise ValueError("nodes 참조 항목 ref.name은 120자 이하여야 합니다.")
        ver = ref.get("version")
        if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
            raise ValueError("nodes 참조 항목 ref.version은 1 이상의 정수여야 합니다.")
        if set(n.keys()) - {"ref"}:
            raise ValueError(
                "nodes 참조 항목은 ref 외 키를 가질 수 없습니다(직접 설정과 혼합 금지)."
            )
        return {"ref": {"name": ref["name"], "version": ver}}

    @staticmethod
    def _normalize_node(n: Any) -> dict[str, Any]:
        """단일 nodes 항목을 화이트리스트·상한 검증 후 정규화 dict로 반환.
        `ref` 키가 있으면 라이브러리 참조 변형(스펙 316)으로 별도 검증."""
        if isinstance(n, dict) and "ref" in n:
            return AgentConfig._normalize_node_ref(n)
        if (
            not isinstance(n, dict)
            or not isinstance(n.get("prompt"), str)
            or not n["prompt"].strip()
        ):
            raise ValueError("nodes 항목은 비어있지 않은 문자열 prompt가 필요합니다.")
        if len(n["prompt"]) > 20000:
            raise ValueError("nodes 항목 prompt는 20000자 이하여야 합니다.")
        node: dict[str, Any] = {"prompt": n["prompt"]}
        AgentConfig._apply_node_scalar_fields(n, node)
        AgentConfig._apply_node_list_fields(n, node)
        return node  # model_cfg 등 화이트리스트 밖 키는 여기서 드롭(저장 안 됨 → 에코 0)

    @field_validator("nodes")
    @classmethod
    def _check_nodes(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """노드형 노드 명세 검증·정규화(스펙 259/260/261 + codex 259-261 후속 하드닝) — 배열(≤50)·각
        항목 dict에 비어있지 않은 문자열 prompt 필수. **키 화이트리스트**로 알려진 필드만 보존한다
        (model_cfg 등 임의 키 저장·에코 차단 = 저장-비밀 풋건 봉인, codex P3) + 필드별 상한(무한
        페이로드 DoS 표면 축소, codex P2 — nodes 개수만 캡하면 필드 크기는 무제한이었음). 의미 검증
        (모델 존재·도구 유효성)은 런타임(플랫폼 모델 해석·impl normalize_nodes)이 방어."""
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("nodes는 배열이어야 합니다.")
        if len(v) > 50:
            raise ValueError("nodes는 50개 이하여야 합니다.")
        return [cls._normalize_node(n) for n in v]

    @field_validator("toolPolicy")
    @classmethod
    def _check_tool_policy(cls, v: dict[str, Any]) -> dict[str, Any]:
        """도구 승인 오버라이드 구조·크기 강제(스펙 177 P2). 위반=422, 정규화 반환.
        키=cap_id, 값={approval:{required?:bool, approver?:"admin"|"self"}}. approval만 인식(그 외 폐기).
        의미 없는 빈 항목은 정규화 시 제거. **완화 권한 판정은 여기서 안 함**(agents CRUD가 admin 게이트)."""
        if not isinstance(v, dict):
            raise ValueError("toolPolicy는 객체여야 합니다.")
        if len(v) > 200:
            raise ValueError("toolPolicy는 항목 200개 이하여야 합니다.")
        out: dict[str, Any] = {}
        for cap, entry in v.items():
            if not isinstance(cap, str) or len(cap) > 200 or not isinstance(entry, dict):
                raise ValueError("toolPolicy 항목은 {cap_id: {approval:{...}}} 형식이어야 합니다.")
            appr = entry.get("approval")
            if not isinstance(appr, dict):
                continue  # approval 없는 항목은 무의미 → 폐기(정규화)
            norm: dict[str, Any] = {}
            if "required" in appr:
                norm["required"] = bool(appr["required"])
            av = appr.get("approver")
            if av in ("admin", "self"):
                norm["approver"] = av
            elif av is not None:
                raise ValueError("approver는 'admin' 또는 'self'여야 합니다.")
            if norm:
                out[cap] = {"approval": norm}
        return out


class AgentCreate(BaseModel):
    name: str = Field(max_length=200)  # 식별 이름(규칙, 스펙 148) — DB String(200) 정합
    description: str | None = Field(
        default=None, max_length=200
    )  # 설명(자유 표기, 스펙 210) — 표시는 name 단독
    config: AgentConfig = Field(default_factory=AgentConfig)


class AgentUpdate(BaseModel):
    """편집 = 초안(draft) 버전에 저장."""

    name: str | None = Field(default=None, max_length=200)  # 식별 이름(규칙, 스펙 148)
    description: str | None = Field(
        default=None, max_length=200
    )  # 설명(자유 표기, 스펙 210) — None=미변경("" = 비우기)
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
    description: str | None = None  # 설명(자유 표기, 스펙 210) — 표시는 name 단독
    source: str
    model: str
    persona: str  # 페르소나 이름(블록 참조, UI 표시용)
    temperature: float | None = None  # 에이전트 영속 온도(스펙 077). None=자동(모델 등록값)
    systemPrompt: str = ""  # 해석된 시스템 프롬프트 본문(런타임이 쓰는 것 = 저장 시점 스냅샷)
    personaStale: bool = (
        False  # 스냅샷이 현재 원본 페르소나와 다름(스펙 161) — 로컬만 계산, 맵 미주입시 False
    )
    historyDepth: int
    persistHistory: bool = True
    ephemeral: bool = False
    suggestedPrompts: list[str] = Field(default_factory=list)  # 플그 추천 명령어(스펙 238)
    impl: str | None = None  # in-process 커스텀 런타임 키(스펙 085) — 폼 재로드/라운드트립 보존용
    # 공통 인터페이스 준수 분류(스펙 089) — 파생값(저장 안 함). conforming=준수(default/적합 impl),
    # non_conforming=A2A 원격(정당한 다른 종류), config_error=impl 선언했으나 미해결(설정 실패).
    conformance: str = "conforming"
    memories: list[str] = Field(default_factory=list)
    vectorTables: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    tools: list[str] = Field(
        default_factory=list
    )  # 직접형 도구 단위 배선(스펙 276, 폼 재로드/왕복 보존)
    capabilities: list[str] = Field(
        default_factory=list
    )  # 능력 브로커 allowlist(스펙 106, 폼 재로드용)
    toolPolicy: dict[str, Any] = Field(
        default_factory=dict
    )  # 도구 승인 오버라이드(스펙 177 P2, 폼 재로드용)
    artifactSpec: dict[str, Any] | None = (
        None  # 노코드 산출물형 필드 명세(스펙 190, 폼 재로드/라운드트립 보존)
    )
    nodes: list[dict[str, Any]] | None = (
        None  # 노드형 파이프라인 노드 명세(스펙 259, 폼 재로드/라운드트립 보존)
    )
    # 노드 참조 해석 결과(스펙 316, 파생·읽기 전용 — 단건 조회만 계산). 오버라이드 패널이 참조
    # 노드의 **유효 설정**을 보여주는 근거. 미해결 참조가 있으면 None(조회 자체는 막지 않음 —
    # 고치러 들어온 화면을 잠그지 않는다. 실행 시점엔 422로 정직 실패).
    resolvedNodes: list[dict[str, Any]] | None = None
    ragMinScores: dict[str, float] = Field(
        default_factory=dict
    )  # 컬렉션별 문서 검색 최소 유사도(스펙 191 v2, 왕복 보존)
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
    token: str | None = (
        None  # 원격 호출 크레덴셜(있으면 crypto.encrypt 저장). 카드가 인증 불요면 None.
    )


class RegisterExternalAgentIn(BaseModel):
    """외부 A2A 에이전트 등록 — 카드 URL만 받아 fetch·검증 후 등록(026, 1차). 057 이후 deprecated(connect로 대체)."""

    cardUrl: str
    token: str | None = (
        None  # 외부 호출 크레덴셜(있으면 crypto.encrypt 저장). 카드가 인증 불요면 None.
    )


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


class FeedbackOut(BaseModel):
    rating: Literal["up", "down"]
    reason: str = ""


class MessageFeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    # 이유 상한(codex 209 F3) — 무제한이면 저장/응답 팽창. 사유는 짧은 메모라 2000자면 충분.
    reason: str = Field(default="", max_length=2000)


class MessageOut(BaseModel):
    id: uuid.UUID | None = None  # 스펙 209 — 피드백 부착 대상(구 응답엔 없어 optional)
    role: str
    content: str
    trace: dict[str, Any] | None = None
    feedback: FeedbackOut | None = None  # 스펙 209 — 요청 사용자의 이 메시지 피드백(없으면 None)


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
    approver: str | None = None  # 승인자(스펙 177 P2) — "admin"=관리자·"self"=본인. UI 태그 표기용.
    resolvedAt: str | None = None  # 처리 시각(스펙 181, 감사) — 미처리면 None
    resolvedBySelf: bool | None = (
        None  # 처리자=요청자면 True(본인), 다르면 False(관리자), 미처리 None
    )


class ApprovalPage(BaseModel):
    # 승인 페이지 응답(스펙 251) — 세션 페이지와 같은 계약({items, total}).
    items: list[ApprovalOut]
    total: int


class ResolveIn(BaseModel):
    decision: Literal["approve", "reject"]


# ----------------------------- 채팅 -----------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatFormSubmission(BaseModel):
    """산출물형 폼 제출(스펙 188 P2) — 대기 중 폼 프레임(formId)에 대한 값. 서버가 pending의
    필드 명세로 검증(값∈후보) 후 Command(resume={"type":"form",...})로 그래프를 재개한다."""

    formId: str
    values: dict


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    sessionId: str | None = None  # 이어서 대화할 세션(없으면 새로 생성)
    # mem0 user_id 축은 더는 클라이언트가 보내지 않는다(스펙 032). chat 핸들러가 인증 주체
    # (current_principal)에서 도출한다: 쿠키 유저면 str(user.id)(UUID), 머신 토큰이면 None(세션 단기).
    # Playground "Proxy" 세션 한정 오버라이드(스펙 025). **web 에이전트에만** 적용, 화이트리스트
    # 키만 의미(model/temperature/systemPrompt/mcps/memories/historyDepth). 저장된 에이전트는 불변.
    # 코드 에이전트는 원격 실행이라 무시(bypass).
    overrides: dict | None = None
    # 산출물형 폼 제출(스펙 188 P2) — 이중 입력의 폼 입구. 텍스트 입구는 messages 그대로.
    form: ChatFormSubmission | None = None
    # 버전 지정 실행(스펙 242) — 지정하면 그 AgentVersion의 config로 실행(초안 미리보기·버전별 테스트).
    # 내부(관리 API) 전용 축: A2A·공개 서빙 경로는 이 필드가 없어 활성 버전만 나간다(외부 경계 공짜).
    version: str | None = None


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


class PolicyIn(BaseModel):
    """능력 부여/회수 입력(스펙 177 P3). subject=역할명 또는 유저 id, object=`capability:...`.

    보안 경계는 라우트(user_admin.grant_policy)가 강제 — object는 `capability:`로 시작하고
    와일드카드(*) 불가, action은 invoke 고정. 이 UI로 임의 리소스 권한·(*,*) 상승을 못 준다."""

    subject: str = Field(min_length=1, max_length=200)  # 역할명(member 등) 또는 유저 UUID 문자열
    object: str = Field(min_length=1, max_length=200)  # capability:{kind}[:{name}]
    action: str = Field(default="invoke", max_length=40)


class PolicyOut(BaseModel):
    subject: str
    object: str
    action: str


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
