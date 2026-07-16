"""RAG 라우트 — 도메인별 모듈 분할(스펙 381, 캠페인 374 T2).

`router`(단일 APIRouter)는 shared에 정의, 도메인 모듈이 데코레이터로 라우트 등록. 여기서 도메인
모듈을 import해 등록을 발화하고, 외부가 쓰는 심볼(router·sweep·resolve)을 재수출한다."""

from . import collections, documents, reindex, search  # noqa: F401
from .shared import resolve_search_collection, router, sweep_zombie_ingests  # noqa: F401
