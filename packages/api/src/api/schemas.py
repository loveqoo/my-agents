"""Pydantic 입출력 스키마 (007 도메인)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ORM = {"from_attributes": True}


# ----------------------------- 빌딩 블록 -----------------------------
class PersonaIn(BaseModel):
    name: str
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


class VectorTableIn(BaseModel):
    name: str
    model: str | None = None
    source: str | None = None
    dims: int | None = None
    rows: int = 0
    status: str = "synced"
    body: str = ""


class VectorTableOut(VectorTableIn):
    id: uuid.UUID
    model_config = ORM


class PermissionIn(BaseModel):
    name: str
    scope: str | None = None
    approver: Literal["user", "admin"] = "user"
    body: str = ""


class PermissionOut(PermissionIn):
    id: uuid.UUID
    model_config = ORM


class McpServerIn(BaseModel):
    name: str
    source: Literal["local", "external"] = "local"
    transport: Literal["stdio", "http"] = "stdio"
    url: str | None = None
    endpoint: str | None = None
    tools: list[str] = Field(default_factory=list)
    enabled_tools: list[str] = Field(default_factory=list)
    status: str = "connected"
    published: bool = False
    auth: str | None = None


class McpServerOut(McpServerIn):
    id: uuid.UUID
    model_config = ORM


class McpPublishIn(BaseModel):
    published: bool


class ModelProbeIn(BaseModel):
    base_url: str = ""
    api_key: str | None = None
    model_id: str = ""
    kind: Literal["chat", "embedding"] = "chat"


class ModelProbeResult(BaseModel):
    ok: bool  # 도달 + 인증 성공
    reachable: bool
    modelAvailable: bool  # 기능 검증 통과 (chat: 목록 존재 / embedding: 임베딩 호출 성공)
    latencyMs: int
    detail: str = ""  # 상태/일반 메시지 (비밀 미포함)
    dims: int | None = None  # 임베딩 벡터 차원 (kind=embedding 성공 시)


# ----------------------------- 모델 레지스트리 -----------------------------
class ModelIn(BaseModel):
    name: str
    provider: str = "openai-compatible"
    base_url: str = ""
    api_key: str | None = None
    model_id: str = ""
    kind: Literal["chat", "embedding"] = "chat"
    is_default: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class ModelOut(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    base_url: str
    api_key: str | None = None  # 마스킹되어 내려옴
    model_id: str
    kind: str
    is_default: bool
    params: dict[str, Any] = Field(default_factory=dict)


# ----------------------------- 에이전트 -----------------------------
class AgentConfig(BaseModel):
    model: str = "local-mlx"
    persona: str = ""  # 페르소나 이름(블록 참조)
    memories: list[str] = Field(default_factory=list)
    vectorTables: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    historyDepth: int = 20
    persistHistory: bool = True  # 대화를 DB에 저장할지(끄면 윈도우 모드)


class AgentCreate(BaseModel):
    name: str
    config: AgentConfig = Field(default_factory=AgentConfig)


class AgentUpdate(BaseModel):
    """편집 = 초안(draft) 버전에 저장."""

    name: str | None = None
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
    name: str
    source: str
    model: str
    persona: str  # 페르소나 이름(블록 참조, UI 표시용)
    systemPrompt: str = ""  # 해석된 시스템 프롬프트 본문(런타임이 쓰는 것)
    historyDepth: int
    persistHistory: bool = True
    memories: list[str] = Field(default_factory=list)
    vectorTables: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
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


class RegisterExternalAgentIn(BaseModel):
    """외부 A2A 에이전트 등록 — 카드 URL만 받아 fetch·검증 후 등록(026, 1차)."""

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
