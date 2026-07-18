# codex 자문 원문 — rag/shared.py 리팩터 (2026-07-19, 스펙 398 입력)

[단계 5 — Verification] read-only로 코드와 소비자만 확인했습니다.

**판정**
`shared.py`의 핵심 결함은 “공유” 자체보다 “공유라는 이름 아래 서로 다른 상태기계가 같은 파일에 갇힌 것”입니다. 현재 파일은 스키마 가드, 모델 검증, 재색인 CAS, 검색 해석, 배경 인제스트, 업로드 캡, 라우터까지 섞여 있어 응집도와 이름이 실제 경계를 속입니다. 특히 `router = APIRouter(...)`가 [shared.py:40](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/shared.py:40)에 있는 것은 명백히 나쁩니다. 라우터는 “공용 유틸”이 아니라 패키지 조립점입니다.

외부 계약은 얇습니다. 실제 런타임 외부 소비는 `main.py`의 `rag.sweep_zombie_ingests()` [main.py:84](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/main.py:84), `eval_runs.py`의 `resolve_search_collection` [eval_runs.py:267](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runs.py:267), FastAPI router 재수출뿐입니다. 반면 내부 5형제는 `.shared import ...`에 강하게 묶여 있습니다. 따라서 이전 “큰 파일 분할”처럼 shared 파사드를 오래 유지하는 쪽보다, `rag` 내부 import를 가족 모듈로 직접 재배선하는 쪽이 더 맞습니다. 단, [__init__.py:14](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/__init__.py:14)의 평면 표면 복원 계약 때문에 `api.rag._acquire_reindex_lock` 같은 테스트 표면은 당분간 보존해야 합니다.

**권장 분할**
- `rag/router.py`: `router = APIRouter(...)`만. `collections/documents/reindex/search`가 여기서 import.
- `rag/schema_guards.py`: `_SCHEMA_MAX_CHARS`, `_SCHEMA_BANNED_KEYS`, `_has_banned_key`, `_check_entity_schema`.
- `rag/embedding_models.py`: `_dim_mismatch`, `_embedding_model`, `_validate_embedding_model`; `_load_collection`은 여러 가족이 쓰므로 `collection_loaders.py` 또는 `collections_core.py`.
- `rag/reindex_core.py`: `_LOCKABLE_STATUSES`, `_reject_if_reindexing`, `_acquire_reindex_lock`, `_set_collection_status`, `_embed_with_model`, `_record_reindex_event`, `_do_reindex`, `_resolve_reindex_model`, `_resolve_rechunk`, `_reject_inflight_ingest`, `_reject_blobless_docs`.
- `rag/search_resolution.py`: `resolve_search_collection`.
- `rag/ingest_core.py`: `_doc_editable`, `_parse_entity_rows`, `_split_chunks`, `_embed_chunks`, `_persist_chunks`, `_mark_ingest_error`, `_execute_ingest`, `sweep_zombie_ingests`, `_load_editable_doc`.
- `rag/limits.py`: `MAX_UPLOAD_BYTES`, `_content_length_guard`.

`shared.py`는 최종적으로 없애는 게 맞습니다. 중간 단계에서는 `shared.py`를 얇은 compatibility shim으로 남겨도 되지만, 내부 5형제는 새 모듈을 직접 import해야 합니다. 그렇지 않으면 파일명만 바뀌고 “공용 잡탕” 계약은 그대로 남습니다.

**동작보존 함정**
- 재색인 락: `_acquire_reindex_lock`의 원자 `UPDATE ... WHERE status IN ("empty","ready","error")` [shared.py:175](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/shared.py:175)는 `reindex_core.py`로 `_LOCKABLE_STATUSES`와 함께 이동해야 합니다. 상수만 다른 파일에 남기면 가장 위험합니다.
- 상태 전이: `reindexing → ready/error`, `parsing → embedding → ready/error`, `empty/ready/error`가 서로 맞물립니다. 특히 `_reject_inflight_ingest`는 `parsing`과 `embedding` 둘 다 봐야 합니다 [shared.py:356](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/shared.py:356).
- 인제스트 실패 마킹: `_execute_ingest`의 외곽 try와 `_mark_ingest_error`는 분리 중 예외 범위를 좁히면 `parsing` 영구 잔류가 재발합니다 [shared.py:574](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/shared.py:574).
- 좀비 스윕: `sweep_zombie_ingests`는 main lifespan 소비가 있으므로 공개 재수출 유지가 필요합니다 [shared.py:622](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/shared.py:622).
- 업로드 캡: `MAX_UPLOAD_BYTES`는 POST upload와 PUT content 양쪽에서 쓰입니다 [documents.py:31](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/documents.py:31). `limits.py`로 빼면 두 입구와 `_content_length_guard`가 같은 값을 봐야 합니다.
- 엔티티 스키마: ReDoS 금지키와 20k cap은 생성/수정 양쪽 소비가 있습니다 [collections.py:70](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/collections.py:70), [collections.py:131](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/rag/collections.py:131).

**권장 순서**
1. `router.py`와 `limits.py`부터 분리. 위험이 낮고 결함이 선명합니다.
2. `schema_guards.py` 분리. 순수 함수라 표적 검증이 쉽습니다.
3. `search_resolution.py` 분리. 외부 계약이 얇지만 `eval_runs.py` 소비가 있으니 `api.rag.resolve_search_collection` 재수출 확인.
4. `embedding_models.py`/`collection_loaders.py` 분리. 컬렉션 생성·검색·재색인이 모두 닿아 import 순환을 조심.
5. `ingest_core.py` 분리. 배경 잡과 실패 마킹 때문에 중간 위험.
6. `reindex_core.py`는 마지막. CAS, 상태 전이, 원자 스왑, 이력 기록이 몰려 있어 가장 위험합니다.

**표적 verify**
격리 대장 기준으로 `verify_036`, `verify_037`, `verify_072`는 현재 KNOWN_DRIFT입니다 [run_suite.py:78](/Users/anthony/Repository/github/loveqoo/my-agents/tests/run_suite.py:78). 리팩터 회귀 판정용 주력은 `verify_149_entity_rag.py`, `verify_312_reindex.py`, `verify_313_zero_downtime.py`, `verify_331_document_edit.py`, `verify_332_entity_edit.py`, `verify_334_background_ingest.py`입니다. 추가로 `verify_140_rag_eval.py`는 격리되어 있으나 `resolve_search_collection` 소비자라 import 표면 확인용으로 따로 대조해야 합니다 [run_suite.py:57](/Users/anthony/Repository/github/loveqoo/my-agents/tests/run_suite.py:57).

이번 턴에서는 read-only 계약 때문에 verify 실행은 하지 않았습니다. `git status`도 macOS 개발자도구 캐시 파일 생성이 막혀 실패했습니다.
