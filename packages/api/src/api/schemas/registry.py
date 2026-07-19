"""schemas.registry — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from .base import AuditOut


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


class ProviderOut(AuditOut):
    id: uuid.UUID
    name: str
    protocol: str
    base_url: str
    api_key: str | None = None  # 마스킹되어 내려옴
    kind: str = "remote"  # local|mock|remote
    description: str = ""
    version: int = 1  # 스펙 369
    modelCount: int = 0  # 매달린 모델 수(삭제 차단 안내·표시용)


# ----------------------------- 모델 레지스트리 -----------------------------
class ModelIn(BaseModel):
    name: str
    provider_id: uuid.UUID  # 연결처는 provider에서 상속
    model_id: str = ""
    kind: Literal["chat", "embedding"] = "chat"
    is_default: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    # 능력 선언(스펙 408) — 2층 원칙 능력 층(오버라이드 불가 사실).
    capabilities: dict[str, Any] = Field(
        default_factory=lambda: {"streaming": True, "thinking": False, "vision": False}
    )
    meta: dict[str, Any] = Field(default_factory=dict)  # models.dev 카탈로그 메타(스펙 047 #7)


class ModelOut(AuditOut):
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
    capabilities: dict[str, Any] = Field(
        default_factory=lambda: {"streaming": True, "thinking": False, "vision": False}
    )  # 능력 선언(스펙 408)
    meta: dict[str, Any] = Field(
        default_factory=dict
    )  # 카탈로그 파생(context·modalities·cost·caps)
    version: int = 1  # 스펙 369


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
