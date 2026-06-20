"""Pydantic 입출력 스키마."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AgentParams(BaseModel):
    """에이전트 모델 파라미터 (생성 시 검증)."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class AgentCreate(BaseModel):
    name: str
    persona: str
    params: AgentParams = Field(default_factory=AgentParams)


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    persona: str
    params: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
