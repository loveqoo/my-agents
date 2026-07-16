"""models.rag — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..audit import AuditMixin
from .base import RAG_EMBED_DIMS, Base, _pk

if TYPE_CHECKING:  # Collection.embedding_model 관계의 문자열 forward-ref 해결(런타임은 레지스트리)
    from .registry import ModelConfig


class Collection(AuditMixin, Base):
    """RAG 지식 컬렉션 — 문서를 임베딩해 의미 검색에 쓰는 단위(스펙 036, vector_tables 재생).

    임베딩 모델 1개로 묶이며 `dims`는 생성 시 probe 실측으로 고정(차원 트랩 대응, 스펙 020 함정3).
    하위 Document·Chunk를 CASCADE로 소유한다. 에이전트 config의 `vectorTables`(이름 목록)가 이
    컬렉션을 참조한다 — 런타임 retrieval 배선은 037.
    """

    __tablename__ = "collections"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)  # 식별 이름(규칙, 스펙 148)
    # 종류 축(스펙 149): document=파일 파싱·청킹 | entity=JSONL 행 단위(1행=1청크, meta 동반).
    # 생성 후 불변(저장 형태가 다름 — 임베딩 모델과 동급). server_default=마이그레이션과 정합
    # (metadata와 alembic의 스키마 diff 방지 — autogenerate 기준, codex 149 Low).
    kind: Mapped[str] = mapped_column(String(20), default="document", server_default="document")
    # 엔티티 행 검증용 JSON Schema(선택, 스펙 149) — 등록 시 업로드 행 전수 검증(내용물 드리프트 차단).
    entity_schema: Mapped[dict | None] = mapped_column(JSONB, default=None)
    # 소유자(스펙 112) — 요청 주체(auth User UUID str). None=레거시/admin-저작=**admin 전용**(fail-closed,
    # learning 070). 브로커 능력 호출 시 소유자 본인 or 특권(admin/superuser)만. 생성 시 1회 스탬프·이전 금지(069).
    owner_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    description: Mapped[str] = mapped_column(Text, default="")
    # 이 컬렉션을 만들 때 쓴 임베딩 모델 — 037 질의 시 같은 모델로 임베딩해야 정합. 모델 삭제 차단(RESTRICT).
    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"), nullable=False
    )
    dims: Mapped[int] = mapped_column(
        Integer
    )  # 생성 시 probe 실측으로 박제(= rag_chunks 컬럼 차원)
    # 청킹도 전략 — 컬렉션별로 사용자 수정 가능(기본 1000자/200 오버랩). 인제스트 시 이 값을 읽어 분할.
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=200)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)  # 비정규화 집계 캐시
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="empty")  # empty|ingesting|ready|error

    embedding_model: Mapped["ModelConfig"] = relationship()
    documents: Mapped[list["Document"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", passive_deletes=True
    )


class Document(AuditMixin, Base):
    """RAG 컬렉션에 인제스트된 업로드 파일(스펙 036). 청크를 CASCADE로 소유."""

    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _pk()
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(400))
    content_type: Mapped[str | None] = mapped_column(String(120), default=None)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="parsing"
    )  # parsing|embedding|ready|error
    error: Mapped[str | None] = mapped_column(Text, default=None)  # 실패 사유 보존(no silent death)

    collection: Mapped["Collection"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(AuditMixin, Base):
    """문서 청크 + 임베딩 벡터(전용 pgvector 저장소, 스펙 036).

    `embedding`은 `Vector(RAG_EMBED_DIMS)`로 차원 고정. insert 전 길이 검증으로 차원 불일치를
    명시적으로 막는다(조용한 죽음 방지). HNSW cosine 인덱스는 037 retrieval에서 본격 사용.
    """

    __tablename__ = "rag_chunks"
    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 질의 필터용 비정규화(037에서 컬렉션 단위 검색) — document 경유 join 없이 바로 필터.
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, default=0)  # 문서 내 순번(엔티티=JSONL 행 번호)
    text: Mapped[str] = mapped_column(Text, default="")
    # 엔티티 메타데이터(스펙 149) — JSONL 행의 metadata 원본(각 테이블 id 등). 문서형은 None.
    # 검색 hit에 동반 반환되어 유사도 검색 결과로 원본 행을 특정할 수 있게 한다.
    meta: Mapped[dict | None] = mapped_column(JSONB, default=None)
    embedding: Mapped[list[float]] = mapped_column(Vector(RAG_EMBED_DIMS))

    document: Mapped["Document"] = relationship(back_populates="chunks")


class DocumentBlob(AuditMixin, Base):
    """문서 원본 바이트(스펙 312) — 재청킹(청크 크기·겹침 변경)에 원본이 필요해 인제스트 시 보존.

    Document 행은 목록 조회에서 자주 로드되므로 큰 바이트를 분리(1:1, document_id=PK). 청크는
    text만 저장돼 모델 교체(재임베딩)엔 충분하지만, **재청킹은 원본에서 다시 잘라야** 하므로 보존.
    이 기능 이전에 올린 문서는 blob이 없다 → 재청킹 불가(소급 한계, UI 표기)."""

    __tablename__ = "document_blobs"
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class CollectionReindexEvent(AuditMixin, Base):
    """재인덱싱 이력(스펙 312) — 컬렉션의 임베딩 모델·청크 정책 계보. 런을 뒤지지 않아도
    "언제 뭘로 바꿨나"가 보인다. 모델 삭제 후에도 이름 박제로 계보 표기(EvalRun.agent_name 선례).
    성공·실패 모두 남긴다(no silent — 왜 못 바꿨나 추적)."""

    __tablename__ = "collection_reindex_events"
    id: Mapped[uuid.UUID] = _pk()
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    from_model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    to_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    to_model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    # 청크 정책 계보(문서형만 유의미 — 엔티티는 1행=1청크). 미변경 시 from==to.
    from_chunk_size: Mapped[int | None] = mapped_column(Integer, default=None)
    from_chunk_overlap: Mapped[int | None] = mapped_column(Integer, default=None)
    to_chunk_size: Mapped[int | None] = mapped_column(Integer, default=None)
    to_chunk_overlap: Mapped[int | None] = mapped_column(Integer, default=None)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)  # 재인덱싱 결과 청크 수
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | error
    error: Mapped[str | None] = mapped_column(Text, default=None)
    owner_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
