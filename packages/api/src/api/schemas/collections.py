"""schemas.collections — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .base import ORM, AuditOut, _require_non_blank


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


class CollectionOut(AuditOut):
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


class DocumentOut(AuditOut):
    id: uuid.UUID
    collection_id: uuid.UUID
    filename: str
    content_type: str | None = None
    byte_size: int
    chunk_count: int
    status: str
    error: str | None = None
    # 스펙 331 — 런타임 수정 가능 여부(문서형·비PDF·원본 blob 보존). ORM 속성이 아니라 라우트가
    # 계산해 채운다(ORM 직렬화 경로는 False 기본 — list_documents가 정본).
    editable: bool = False
    # 스펙 435 — 인제스트 진행률 {done, total}(청크 단위). 진행 중일 때만 채워지고(프로세스-로컬 맵),
    # 대기·완료·오류면 None. editable과 같이 **라우트가 계산해 채우는** 필드(ORM 속성 아님).
    progress: dict[str, int] | None = None
    model_config = ORM


class DocumentPageOut(BaseModel):
    """문서 페이지 목록(스펙 128) — 문서는 증가 축이라 서버 페이지네이션(세션·메모리와 동형 패턴)."""

    items: list[DocumentOut]
    total: int  # q(파일명 부분일치) 적용 후 전체 건수
    # 컬렉션 전체의 처리 중(parsing/embedding) 문서 수(스펙 334, codex P2) — 현재 페이지에 안
    # 보여도 폴링이 서야 하므로 페이지·검색어와 무관한 전역 신호로 싣는다.
    processing: int = 0


class DocumentContentOut(BaseModel):
    """문서 원문 조회(스펙 331) — 편집 가능(문서형·비PDF·원본 보존·UTF-8)이면 text 동반,
    아니면 text=None + reason(사유)로 정직 표면화."""

    id: uuid.UUID
    filename: str
    editable: bool
    text: str | None = None
    reason: str | None = None  # editable=false 사유(UI 툴팁)


class DocumentEditIn(BaseModel):
    text: str = Field(min_length=1)


class DocumentEditOut(BaseModel):
    """문서 수정 결과(스펙 331) — 부분 재임베딩 통계를 실측 그대로 노출(reused+reembedded=chunks)."""

    document: DocumentOut
    chunks: int  # 재청킹 결과 청크 수
    reembedded: int  # 새로 임베딩한 청크 수(내용 변경분)
    reused: int  # 기존 벡터 재사용 청크 수(내용 동일)


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
