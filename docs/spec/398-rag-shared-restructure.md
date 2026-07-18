# 398 — rag/shared.py 해체(공용 잡탕 소멸 — 가족별 응집 모듈)

> 상태: **완료** · 2026-07-19 (승인 후 P1~P7 실행 → codex 적대 코드 발견 0건)
> 발단: 잔여 중형 1위 — 663줄·MI 34.3(잔여 최저 2위). **C급 0(게이트 이미 깨끗)** — 이번
> 회전의 문제는 복잡도가 아니라 응집도: "shared"라는 이름 아래 서로 다른 상태기계 동거.
> 방식: 8회전 — codex 자문(`.dev/reviews/398-rag-shared/codex-consult.md`) → 승인 → 실행 → 적대.

## 구조 판단(codex — 이전 회전들과 다른 처방)

- **shared.py는 파사드 유지가 아니라 소멸.** 외부 계약이 얇고(main의 sweep·eval_runs의
  resolve·router 재수출뿐) 소비자가 rag 패키지 내부 5형제뿐 — "파일명만 바꾸면 공용 잡탕
  계약이 그대로 남는다". 내부 5형제 import를 새 가족 모듈로 **직접 재배선**.
- `router = APIRouter(...)`가 shared에 사는 것이 명백한 결함 — 라우터는 공용 유틸이 아니라
  패키지 조립점(`rag/router.py`로).
- 평면 표면(`api.rag.X` — 테스트가 소비)은 __init__의 서브모듈 승격 루프가 자동 보존 —
  새 모듈을 루프에 추가하고 `from .shared import` 줄만 갱신.

## 처방(위험 오름차순 — codex 순서, 7모듈)

- **P1** `rag/router.py`(router 조립점) + `rag/limits.py`(MAX_UPLOAD_BYTES·_content_length_guard
  — POST 업로드·PUT 편집 양 입구가 같은 값).
- **P2** `rag/schema_guards.py`: _SCHEMA_MAX_CHARS·_SCHEMA_BANNED_KEYS·_has_banned_key·
  _check_entity_schema(ReDoS 금지키 — 생성·수정 양쪽 소비).
- **P3** `rag/search_resolution.py`: resolve_search_collection(eval_runs 소비 — api.rag 재수출 확인).
- **P4** `rag/embedding_models.py`: _dim_mismatch·_embedding_model·_validate_embedding_model·
  _load_collection(다가족 공용 로더 동거 — 순환 조심).
- **P5** `rag/ingest_core.py`: _doc_editable·_parse_entity_rows·_split_chunks·_embed_chunks·
  _persist_chunks·_mark_ingest_error·_execute_ingest·sweep_zombie_ingests·_load_editable_doc.
- **P6** `rag/reindex_core.py`(최후·최고 위험 — CAS·상태 전이·원자 스왑·이력):
  _LOCKABLE_STATUSES·_reject_if_reindexing·_acquire_reindex_lock·_set_collection_status·
  _embed_with_model·_record_reindex_event·_do_reindex·_resolve_reindex_model·_resolve_rechunk·
  _reject_inflight_ingest·_reject_blobless_docs.
- **P7** shared.py **삭제** + 내부 5형제·__init__ 재배선.

**OUT**: 상태기계·락·캡 수치·상태 전이 일절 변경 금지. C급 분해 없음(이미 0). 명시 개선 0건.

## 동작보존 함정(codex 목록)

1. 재색인 락의 원자 UPDATE는 **_LOCKABLE_STATUSES와 동일 모듈 동거**(상수만 딴 데 남기면 최위험).
2. 상태 전이 맞물림: reindexing→ready/error · parsing→embedding→ready/error —
   _reject_inflight_ingest는 parsing **과** embedding 둘 다(334 codex P1).
3. _execute_ingest 외곽 try 범위 축소 금지(parsing 영구 잔류 재발 지점).
4. sweep_zombie_ingests는 main lifespan 소비 — api.rag 재수출 유지.
5. MAX_UPLOAD_BYTES는 두 입구+_content_length_guard가 같은 값(한 모듈).
6. _persist_chunks의 조건부 UPDATE(status != reindexing) 선행 계약(312 F1 — P0 유실 방지).

## 완료 기준(수치) — 전부 달성(실측)

- [x] shared.py **소멸**(663→0줄). 신규 7모듈(router 10·limits 27·schema_guards 60·
      embedding_models 84·search_resolution 43·ingest_core 235·reindex_core 254) 전부
      xenon ≤C·**MI 52.3~83.4**(34.3 대폭 초과). 내부 4형제 직접 재배선(파사드 없음).
- [x] 평면 표면 보존: api.rag.X 12심볼 hasattr + codex 실측 **구 shared dir 60개 중 누락 0**
      (rag_ingest·events 등 우연 노출까지 생존 — __init__ 승격 루프).
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51**(1차 1건 실패는 재실행
      판정 결과 실모델 비결정 — 1턴 미영속→재개 접힘 시그니처, RAG 무관 축) + 표적 verify 6종
      (149 엔티티 31건·312 재인덱싱 CAS·313 무중단·331/332 편집·334 배경 인제스트) virgin 그린.

## codex 적대 스팟 리뷰 결과 — 코드 발견 0건

- 유일 P2=랜딩 경고(리뷰 시점 스테이징이 shared 삭제만 staged) — 마감 커밋의 전 파일 동시
  staging으로 해소(코드 결함 아님).
- 확인함(codex): **27개 함수 raw source 전부 HEAD 동일**·조건부 UPDATE 선행 유지·이중 try 범위
  유지·락+상수 동거·평면 표면 60/60·import 사이클 0·소비자 3종(main lifespan·eval_runs·
  models) 생존·상태 전이 맞물림 유지.
