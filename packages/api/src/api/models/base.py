"""에이전트 서비스 도메인 테이블.

빌딩 블록(프롬프트·메모리타입·벡터테이블·권한·MCP 서버)은 개별 테이블,
에이전트는 컬럼 + config jsonb + agent_versions, 그리고 세션/메시지/승인.
지배 스펙: docs/spec/007-real-agent-service.md
"""

import os
import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# RAG 청크 벡터 차원 — pgvector 컬럼은 생성 시 차원이 고정되므로(스펙 020 함정3) 이 값이 곧
# `rag_chunks.embedding` 컬럼 차원이자 Collection 생성 시 허용 차원의 단일 출처다. 기본 임베딩
# 모델(multilingual-e5-large=1024) 출력과 일치해야 한다. mem0(_EMBED_DIMS)와 같은 1024 기본.
RAG_EMBED_DIMS = int(os.environ.get("RAG_EMBED_DIMS", os.environ.get("MEM0_EMBED_DIMS", "1024")))


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
