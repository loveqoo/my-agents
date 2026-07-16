"""RAG 라우트 — 도메인별 모듈 분할(스펙 381, 캠페인 374 T2).

`router`(단일 APIRouter)는 shared에 정의, 도메인 모듈이 데코레이터로 라우트 등록. 여기서 도메인
모듈을 import해 등록을 발화하고, 외부가 쓰는 심볼(router·sweep·resolve)을 재수출한다.

**임포터 무변경(스펙 381 회귀 봉합)**: 분할 전 rag.py는 평면 모듈이라 헬퍼·라우트 핸들러·모듈 임포트가
전부 `api.rag.X`로 닿았다(`from api.rag import _acquire_reindex_lock`, `rag.ingest_document`,
`rag.rag_ingest` 등 — 특히 테스트가 route 핸들러를 직접 호출). 서브모듈의 non-dunder 이름을 패키지
top으로 승격해 그 평면 표면을 그대로 복원한다."""

from . import collections, documents, reindex, search, shared
from .shared import resolve_search_collection, router, sweep_zombie_ingests  # noqa: F401

# 서브모듈에 정의/임포트된 전 심볼을 패키지 top에 재수출 — 평면 모듈 시절 api.rag.X 접근 복원.
for _mod in (shared, collections, documents, reindex, search):
    for _name in dir(_mod):
        if not _name.startswith("__"):
            globals()[_name] = getattr(_mod, _name)
del _mod, _name
