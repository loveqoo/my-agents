"""평가 하네스 요청/응답 스키마(스펙 291 분할 — 리프, 프로젝트 의존 없음).

원 소재: eval_routes.py. 필드별 설계 결정(스펙 번호 주석)은 원문 그대로 보존.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .schemas import AuditOut


class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    kind: str = Field(default="agent", pattern="^(agent|rag)$")
    collection_id: uuid.UUID | None = None  # 스펙 193 — kind=rag면 대상 컬렉션 고정(생성 시 저장)


class DatasetOut(AuditOut):
    id: uuid.UUID
    name: str
    description: str | None
    kind: str
    collection_id: uuid.UUID | None = (
        None  # 스펙 193 — RAG 문제집의 고정 컬렉션(실행 시 재선택 불필요)
    )
    # 스펙 209 P2 후속: 수확 문제집의 출처 에이전트 — 실행 대상을 이 에이전트로 고정(RAG 컬렉션과 동형).
    # 수확은 "이 에이전트 바꾼 뒤 회귀 확인"이 목적이라 재선택 불필요. 일반 문제집=NULL.
    source_agent_pk: uuid.UUID | None = None
    case_count: int = 0
    can_manage: bool = True  # 스펙 178 — 이 유저가 수정/삭제/실행 가능(소유자·특권). UI 버튼 게이트
    generating: bool = (
        False  # 스펙 193 — 문제 자동 생성 진행 중(목록 스피너·드로어 Skeleton·폴링 신호)
    )


class DatasetPageOut(BaseModel):
    items: list[DatasetOut]
    total: int
    any_generating: bool = False  # 이 페이지에 진행 중 문제집이 있나 — 프론트 폴링 신호(스펙 196)


class CaseIn(BaseModel):
    # 스펙 195: 이름은 UI서 제거 — 없으면 서버가 해시(case-xxxxxxxx) 생성(유저 비노출·내부 관리).
    # 성적표엔 질문(input)이 뜨므로 유저는 이름을 볼 일이 없다. update 시 미전송이면 기존 보존.
    name: str | None = Field(default=None, max_length=200)
    input: str = Field(
        min_length=1, max_length=4000
    )  # 모델 프롬프트로 들어감 — 폭주 상한(codex 137 #3)
    asserts: list = Field(default_factory=list, max_length=20)  # 채점 기준 개수 상한
    order_idx: int = Field(default=0, ge=0, le=10_000)


class CaseOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    input: str
    asserts: list
    order_idx: int
    model_config = {"from_attributes": True}


class RunStartIn(BaseModel):
    agent_id: uuid.UUID | None = None  # kind=agent: agents.id (pk)
    collection_id: uuid.UUID | None = None  # kind=rag: 컬렉션 id (스펙 140)
    models: list[str] = Field(default_factory=list, max_length=6)  # 모델 비교(스펙 141, agent 전용)
    # 버전 지정 평가(스펙 242) — 그 AgentVersion config로 실행(초안=배포 전 게이트). None=활성(서빙).
    agent_version: str | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None  # 목록 표시용(조인 채움)
    agent_name: str | None
    model_name: str | None = None  # 모델 오버라이드 박제(스펙 141)
    agent_version: str | None = None  # 실행 시점 활성 버전(스펙 240) — NULL=과거 런
    env: dict | None = None  # 경량 환경 기록(스펙 240, 진단용)
    group_id: uuid.UUID | None = None  # 모델 비교 그룹(스펙 141)
    status: str
    score: float | None
    passed: int
    total: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    can_manage: bool = True  # 스펙 178 — 이 유저가 이 실행(성적표)을 관리 가능(소유자·특권)
    model_config = {"from_attributes": True}


class CaseResultOut(BaseModel):
    case_name: str
    case_passed: bool
    details: list
    obs: dict | None
    model_config = {"from_attributes": True}


class RunDetailOut(RunOut):
    results: list[CaseResultOut] = []


class SuggestIn(BaseModel):
    agent_id: uuid.UUID | None = None  # 스펙 195: rag 문제집은 불필요(고정 컬렉션 사용)
    count: int = Field(default=10, ge=1, le=10)


class HelperStatusOut(BaseModel):
    available: bool
    reason: str | None = None


class HarvestIn(BaseModel):
    agent_id: uuid.UUID


class HarvestCountOut(BaseModel):
    available: int  # 미수확 피드백 수(수확 버튼 배지)
    dataset_id: uuid.UUID | None = None  # 기존 수확 문제집(있으면)
