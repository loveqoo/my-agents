"""schemas.mcp — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..mcp_tool_meta import (
    PARAM_NAME_CAP,
    PARAM_TYPE_CAP,
    TOOL_DESC_CAP,
    TOOL_NAME_CAP,
    TOOL_PARAMS_CAP,
    TOOLS_META_CAP,
)
from .base import ORM, AuditOut


class McpToolParam(BaseModel):
    """도구 파라미터 요약(스펙 151) — args 스키마에서 파생한 표시용. 길이 캡=원격 유래 방어."""

    name: str = Field(max_length=PARAM_NAME_CAP)
    type: str = Field(default="any", max_length=PARAM_TYPE_CAP)
    required: bool = False


class McpToolInfo(BaseModel):
    """도구 메타(스펙 151·375) — 탐색 시점 스냅샷. 캡은 mcp_tool_meta 단일 출처(저장 정규화와 공유)."""

    name: str = Field(max_length=TOOL_NAME_CAP)
    description: str = Field(default="", max_length=TOOL_DESC_CAP)
    params: list[McpToolParam] = Field(default_factory=list, max_length=TOOL_PARAMS_CAP)


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
        입력 경계에서 구조·크기를 강제(서버당 TOOLS_META_CAP개·McpToolInfo 캡). 위반=422, 정규화해 반환."""
        if v is None:
            return v
        if not isinstance(v, dict) or len(v) > TOOLS_META_CAP:
            raise ValueError(f"tools_meta는 도구 {TOOLS_META_CAP}개 이하의 객체여야 합니다.")
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


class McpServerOut(McpServerIn, AuditOut):
    id: uuid.UUID
    owner_id: str | None = None  # 소유자(스펙 112). None=공유/레거시
    can_manage: bool = True  # 요청 주체 수정/삭제 가능(스펙 114, list/get서 계산·기본 True)
    # 서빙 URL(스펙 156) — source=custom이고 레지스트리에 정의가 있을 때만. 외부가 이 URL로 등록·접속.
    # published=False면 아직 서빙 안 되지만(404) UI가 "공개하면 여기로 서빙" 안내에 쓴다. 그 외 None.
    served_url: str | None = None
    version: int = 1  # 스펙 369
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


class McpToolTestIn(BaseModel):
    """MCP 도구 시험 호출(스펙 326) — 상세 드로어 '도구 시험'. args는 도구 시그니처대로."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    # 승인 정책(스펙 177) 걸린 도구는 confirm=True 없이 400 — 시험 통로가 HIL을 소리 없이
    # 우회하지 않게 백엔드에서 강제(프론트 경고는 안내일 뿐).
    confirm: bool = False


class McpToolTestOut(BaseModel):
    """시험 결과 — 실행 경로(build_mcp_tools)의 calls_sink에서 회수(마스킹+캡 동일 적용)."""

    ok: bool
    ms: int = 0
    result: str | None = None  # 성공 시 결과 프리뷰(_sanitize_preview 적용분)
    error: str | None = None  # 실패 사유(스펙 320 — 타입+메시지, 마스킹+캡)
