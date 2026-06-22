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


# ----------------------------- 에이전트 -----------------------------
class AgentConfig(BaseModel):
    model: str = "local-mlx"
    persona: str = ""  # 페르소나 이름(블록 참조)
    memories: list[str] = Field(default_factory=list)
    vectorTables: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    historyDepth: int = 20


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
    persona: str  # 해석된 페르소나 본문(또는 이름)
    historyDepth: int
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


class ExposeIn(BaseModel):
    a2a: bool


class ActivateIn(BaseModel):
    version: str


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
