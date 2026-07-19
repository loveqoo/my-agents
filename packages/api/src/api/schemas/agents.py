"""schemas.agents — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agent.capabilities import clean_setting_params

from .base import AuditOut


# ----------------------------- 에이전트 -----------------------------
class AgentConfig(BaseModel):
    model: str = "mock-llm"  # 미지정 시 기본 모델(스펙 059)
    prompt: str = ""  # 프롬프트 이름(블록 참조)
    temperature: float | None = (
        None  # 에이전트 영속 온도(스펙 077). None=자동(모델 등록 params 적용)
    )
    # 모델 설정 오버라이드(스펙 408 캐스케이드) — 화이트리스트 키(enable_thinking·stream)만 실효.
    # temperature는 위 기존 필드가 에이전트 층 정본(이중 거처 금지). 미명시 키=모델 기본 상속.
    modelParams: dict[str, Any] = Field(default_factory=dict)

    @field_validator("modelParams")
    @classmethod
    def _clean_model_params(cls, v: Any) -> dict:
        """저장 경계에서 화이트리스트 설정 키의 bool만 보존(스펙 409 codex P2③) — 실행부만 거르던
        것을 저장까지 정직화(에코·버전 오염 차단). 노드·세션과 같은 공유 정리기."""
        return clean_setting_params(v)
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
    def _apply_node_model_params(n: dict[str, Any], node: dict[str, Any]) -> None:
        """노드별 모델 설정 오버라이드(스펙 409) — 공유 정리기(화이트리스트 설정 키의 bool만)."""
        clean = clean_setting_params(n.get("modelParams"))
        if clean:
            node["modelParams"] = clean

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
        AgentConfig._apply_node_model_params(n, node)
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
    everOpened: bool = (
        False  # 오픈 이력(스펙 370) — True=영구 불변 보호, False=스크래치(편집이 대체)
    )
    pins: dict[str, int] = Field(default_factory=dict)  # 블록 버전 못박기 {kind:name → ver}
    note: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None


class AgentOut(AuditOut):
    id: uuid.UUID
    agentId: str
    name: str  # 식별 이름(규칙, 스펙 148)
    description: str | None = None  # 설명(자유 표기, 스펙 210) — 표시는 name 단독
    source: str
    model: str
    prompt: str  # 프롬프트 이름(블록 참조, UI 표시용)
    temperature: float | None = None  # 에이전트 영속 온도(스펙 077). None=자동(모델 등록값)
    modelParams: dict[str, Any] = Field(
        default_factory=dict
    )  # 모델 설정 오버라이드(스펙 408 — 폼 재로드용)
    systemPrompt: str = ""  # 해석된 시스템 프롬프트 본문(런타임이 쓰는 것 = 저장 시점 스냅샷)
    # 오픈 버전 pins 중 블록 head가 더 새 버전인 항목(스펙 370 §4 채택 배지) — 단건 GET만 계산.
    stalePins: list[dict[str, Any]] = Field(default_factory=list)
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
    prompt: str = "코드 정의 (SDK)"
    runtime: str | None = None
    repo: str | None = None
    commit: str | None = None
    memories: list[str] = Field(default_factory=list)
    historyDepth: int = 10
    mcps: list[str] = Field(default_factory=list)
