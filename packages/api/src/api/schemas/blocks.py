"""schemas.blocks — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from .base import ORM, AuditOut


# ----------------------------- 빌딩 블록 -----------------------------
class PromptIn(BaseModel):
    name: str = Field(max_length=200)  # 식별 이름(규칙, 스펙 148) — DB String(200) 정합(codex 148)
    description: str | None = Field(
        default=None, max_length=200
    )  # 설명(자유 표기, 스펙 210) — 표시는 name 단독
    tone: str | None = None
    body: str = ""


class PromptOut(PromptIn, AuditOut):
    id: uuid.UUID
    version: int = 1  # 단조 불변 버전(스펙 369)
    model_config = ORM


class BlockVersionOut(AuditOut):
    """블록 버전 이력 1건(스펙 369) — 5종 공유 폴리모픽. payload=그 버전의 저작 내용."""

    id: uuid.UUID
    kind: str
    block_pk: uuid.UUID
    version: int
    payload: dict[str, Any] = Field(default_factory=dict)
    model_config = ORM


class PromptUsageAgentOut(BaseModel):
    """프롬프트를 쓰는 에이전트 1건(스펙 161) — 편집 화면 "사용 에이전트·오래됨" 목록용."""

    id: uuid.UUID
    agentId: str
    name: str
    description: str | None = None
    stale: bool  # 이 에이전트 스냅샷이 현재 프롬프트 본문과 다름
    canManage: bool  # 요청 주체가 이 에이전트를 갱신할 수 있음(스펙 112/114)


class PromptApplyIn(BaseModel):
    agentIds: list[uuid.UUID]  # 이 프롬프트 최신 본문을 반영할 에이전트들


class PromptApplyOut(BaseModel):
    applied: list[uuid.UUID]  # 실제 갱신된 에이전트
    skipped: list[uuid.UUID]  # 관리 불가/미참조로 건너뜀


class MemoryTypeIn(BaseModel):
    key: str
    name: str
    scope: str | None = None
    body: str = ""


class MemoryTypeOut(MemoryTypeIn):
    id: uuid.UUID
    version: int = 1  # 스펙 369
    model_config = ORM
