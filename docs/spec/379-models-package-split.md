# 379 — models.py → 도메인 패키지 분할 (캠페인 374 Tier 2)

## 왜

codex 리뷰 P2(그룹 B): 단일 `models.py`(765줄·30모델)에 블록·RAG·provider/model·MCP·agent·
session·approval·auth·batch·eval 테이블이 모두 있어 bounded context 경계가 없다.

## 무엇

`models.py` → `models/` 패키지로 **verbatim 슬라이싱**. base + 10개 도메인 모듈:

`base`(Base·_pk·RAG_EMBED_DIMS) · `blocks`(3) · `rag`(5) · `registry`(2) · `mcp`(1) · `core`(AppSetting) ·
`agents`(3) · `sessions`(4) · `auth`(3) · `batch`(4) · `eval`(4).

- `__init__.py`가 **모든 모델을 import**해 SQLAlchemy 레지스트리에 등록 + 명시적 re-export —
  `from api.models import X`·`Base`·`RAG_EMBED_DIMS` **기존 그대로**(임포터·alembic env·checkpointer 무변경).
- 모듈 간 관계는 하나뿐 — `Collection.embedding_model → ModelConfig`(rag→registry, 문자열 forward-ref).
  런타임은 레지스트리로 해결, `TYPE_CHECKING` import로 애노테이션/ruff 만족(런타임 import 없음·순환 0).
- 직접 클래스 참조 관계(AgentVersion→Agent·Message→Session)는 동일 모듈이라 무영향.

**동작 불변** — 30모델 그대로, 컬럼·관계·제약 동일. 순수 이동.

## 완료 조건 (동작 불변)

- 30모델 보존(측정) · `configure_mappers()` 성공(전 관계 해결) · metadata 30테이블 · re-export 누락 0 · ruff.
- make test SUITE_OK · e2e 39/39.

## 검증 결과 (2026-07-16 — done)

전부 초록: 30모델 보존·configure_mappers OK·30테이블·Collection.embedding_model→ModelConfig 해결·
re-export 누락 0·app import·ruff·SUITE_OK·e2e 39/39. bounded context 경계 확립.
