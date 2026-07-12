# 312 — 컬렉션 재인덱싱·재청킹 (같은 차원, 배타 잠금)

## 배경 / 문제
컬렉션은 임베딩 모델·차원·청크 정책이 **생성 후 불변**(스펙 149·198). 그래서 mock-embed로 심은
컬렉션은 검색이 형편없어도 모델을 못 바꾸고, 청크 크기·겹침도 못 바꾼다. 실측(2026-07-12):
같은 10편을 진짜 모델(e5)로 다시 심으니 패러프레이즈 질의가 mock 0.0x·무작위 → e5 0.8x·의미 정확.

**검색 품질을 끌어올리려면 임베딩 모델뿐 아니라 청크 크기·겹침도 같이 바꿔가며 테스트**해야 한다
(사용자 확언). 이를 위해 (1) 원본을 저장해 재청킹 가능하게 하고, (2) 모델·청크 파라미터를 바꿔
다시 인덱싱하며, (3) 그 과정 동안 컬렉션을 **배타 잠금**해 일관성을 지키고, (4) 평가 이력은
보존해 설정별 검색 품질을 비교한다.

## 결정 / 스코프

### 1) 같은 차원(1024)만 — pgvector 제약
`rag_chunks.embedding`은 **전역 단일 `Vector(RAG_EMBED_DIMS=1024)`** 컬럼(모든 컬렉션 공유,
스펙 020 함정3). 대상 모델 probe dims ≠ 1024면 거부(`_dim_mismatch` 재사용).
**차원 변경(저장 구조 재설계)은 별도 스펙 — OUT.**

### 2) 원본 저장 → 재청킹 가능
인제스트는 `data(원본 바이트) → _split_chunks(파싱+청킹) → _embed_chunks → _persist_chunks`이고
지금은 원본을 청킹 후 버린다. 청크 크기·겹침을 바꾸려면 원본 바이트가 필요하다. → 인제스트 시
원본을 **별도 blob 테이블 `document_blobs`**(document_id FK·data bytea)에 저장(Document 행은 목록
조회에서 자주 로드되니 큰 바이트 분리). 재청킹은 `_split_chunks`를 새 파라미터로 재실행.

- **청크 크기·겹침은 문서형(document)에만 유효** — 엔티티형은 1행=1청크라 청킹 파라미터 없음
  (movies 같은 엔티티는 모델 교체만). 재청킹 UI는 문서형에만 노출.
- **소급 한계(no silent)**: 이 기능 이전에 올린 문서는 원본 미저장 → 재청킹 불가(재업로드 필요).
  "원본 없는 문서는 재청킹 불가"를 UI에 표기. movies-demo도 원본 저장하려면 로더 재실행.

### 3) 배타 잠금 — 재인덱싱 중 접근 차단 (사용자 요구 2026-07-12)
재인덱싱/재청킹 중에는 벡터가 교체되므로, **다른 접근을 막아 일관성을 지킨다**:
- **획득(CAS)**: `UPDATE collections SET status='reindexing' WHERE id=? AND status IN
  ('ready','empty','error')` — 영향 행 0이면 이미 잠김/인제스트 중 → **409 busy**(TOCTOU 회피,
  check-then-act 경합 금지, [[gate-on-intent-value-not-mutable-baseline]]).
- **잠금 중 차단**: 그 컬렉션의 **검색·인제스트·수정·삭제·또 다른 재인덱싱** 모두 409(명확 사유).
  검색은 에이전트/평가 읽기 경로(`search_collections`)라, 재인덱싱 중이면 조용한 부분결과 대신
  "재인덱싱 중 — 잠시 후" 거절(fail-closed).
- **해제(try/finally)**: 성공→`status='ready'`, 실패→`status='error'`+사유. 절대 잠긴 채 누수 금지.
- **stale 잠금 복구(no silent stuck)**: 프로세스가 재인덱싱 중 죽으면 status='reindexing'이 남는다
  → 부팅 스윕 or 관리자 리셋 액션으로 회수(수동 재인덱싱 재시도 가능하게). 갇힌 상태를 표면화.

### 4) 평가 이력 보존
재인덱싱은 평가 런을 **건드리지 않는다**. (1)안전(삭제=비가역 파괴 지양), (2)eval_runs는 문제집 밑
audit 이력(컬렉션 변경과 독립), (3)`EvalRun.env.collections.<name>.embedding`에 실행 시점 임베딩
모델명이 이미 박제(스펙 240) → mock 옛 런 vs e5 새 런이 그대로 비교 가능. → "재인덱싱하면 과거
평가를 지우나?"의 답: **아니오, 보존**(사용자 직감과 일치).

### 5) 재인덱싱 이력 — 전용 테이블
"언제 뭘로 바꿨나"가 런을 뒤지지 않아도 보이게, 새 테이블 `collection_reindex_events`
(사용자 결정: 테이블로, YAGNI 지남):
- `id`·`collection_id`(FK CASCADE)·`from_model_id`/`from_model_name`·`to_model_id`/`to_model_name`
  ·`from_chunk_size`/`from_chunk_overlap`·`to_chunk_size`/`to_chunk_overlap`·`chunk_count`(결과)
  ·`status`(ok|error)·`error`·`owner_id`·`created_at`.
- 모델 삭제 후에도 이름 박제로 계보 표기(EvalRun.agent_name 선례). `GET /collections/{id}/reindex-events`.

## 구현 (Execution)

### 백엔드
1. **원본 저장(인제스트)**: `ingest_document`에서 `document_blobs`에 원본 바이트 저장(문서 행과 함께).
   기존 문서는 blob 없음(소급 한계 표기 근거).
2. **엔드포인트** `POST /collections/{id}/reindex` body `{embedding_model_id?, chunk_size?, chunk_overlap?}`
   (부분 — 준 것만 변경). 최소 하나는 현재와 달라야(무의미 no-op은 400).
3. **잠금 획득(CAS)** → 아래 원자 수행 → 해제(try/finally). 획득 실패=409.
4. **검증**: 모델 지정 시 kind=embedding·probe dims==1024. 청크 파라미터 지정 시 문서형만 허용
   (엔티티는 400)·범위 검증. 원본 없는 문서 포함 컬렉션에 청크 변경 요청 시 명확 거절/부분 표기.
5. **재인덱싱 코어**:
   - 모델만 변경 → 저장된 `Chunk.text`를 새 모델로 재임베딩(원본 불필요, 빠름).
   - 청크 파라미터 변경(문서형) → `document_blobs` 원본으로 `_split_chunks` 재실행 → 재임베딩 →
     기존 청크 교체(문서별). `chunk_count` 갱신.
   - 각 새 벡터 len==1024 검증(인제스트 가드2 재사용). 실패=error·롤백(반쪽 금지).
6. **원자성**: 새 청크/벡터 전량 계산 후 **한 트랜잭션 스왑** + `Collection.embedding_model_id`/
   `chunk_size`/`chunk_overlap` 갱신. 실패 시 원 상태 온전 롤백.
7. **이력 기록**: 성공/실패 모두 `collection_reindex_events` 삽입(모델·청크 계보·status·error).
8. **접근 차단 배선**: `search_collections`·`ingest_document`·update/delete collection이 status=
   'reindexing'이면 409(잠금 중). stale 잠금 부팅 스윕/리셋.
9. **마이그레이션**: 새 테이블 2개(`document_blobs`·`collection_reindex_events`). 리비전 ID 앞
   스펙 슬롯 충돌 점검(헤더-only 그래프: 단일 head·중복 0·고아 0)·한 번에 완성·DB 측정.

### 프론트 (어드민 UI 버튼)
10. 컬렉션 상세에 **"모델 변경·재인덱싱"** 액션(antd Button+Modal).
    - 모델 선택 = **같은 차원(1024) 임베딩 모델만**(차원 다른 건 비활성+툴팁).
    - 문서형이면 청크 크기·겹침 입력 노출(엔티티형은 숨김). 원본 없는 문서는 재청킹 불가 안내.
    - 확인 카피(긍정문): "새 설정으로 벡터를 다시 만듭니다. 재인덱싱 중에는 이 컬렉션 접근이 잠깁니다.
      기존 평가 이력은 보존됩니다." (부정의 부정 금지 — [[prefer-positive-phrasing-in-copy]].)
    - 진행 상태(status=reindexing) 표시 + 완료/실패 토스트(runWithToast).
    - **재인덱싱 이력 섹션**(모델·청크 계보 A→B·시각·청크 수).

## 검증 (측정 가능 — Verification)
- **모델 교체(실 인프라)**: movies-demo(mock)를 e5로 → 청크 수 불변·벡터 1024·`embedding_model_id`
  스왑·같은 질의 top 결과 개선(점수↑·순위) 수치 단언·평가 런 이력 건수 불변(옛 env=mock·새=e5).
- **재청킹(문서형)**: 문서 컬렉션에 원본 저장 후 chunk_size 변경 → `chunk_count` 변화(재청킹 실증)·
  원본 blob으로 재구성·이력에 청크 계보 기록. 엔티티에 청크 파라미터 → 400.
- **배타 잠금(적대·경합)**: 동시 재인덱싱 2건 → 2번째 409. 재인덱싱 중 검색/인제스트/삭제 → 409.
  성공·실패 **양쪽에서 잠금 해제**(try/finally, 잠긴 채 누수 0). 프로세스 강제 종료 후 stale
  'reindexing' → 스윕/리셋으로 회수. **codex 적대**: CAS 우회(동시 요청 레이스)·반쪽 상태·차원 우회.
- **정적/프론트**: ruff/mypy/tsc/build 클린 · 브라우저 왕복(모델·청크 선택→잠금→진행→이력, 같은차원만
  선택·평가 이력 보존·잠금 중 접근 차단 표시).

## 알려진 경계 (codex 적대 리뷰 — 안전 위반 아닌 미문서 경계, 단일 워커 배포 전제)
- **F1(수정됨, P0)**: 인제스트가 재인덱싱 잠금을 무조건 덮어쓰고 새 청크를 유실할 수 있던 데이터 손실
  → `_persist_chunks`가 커밋 시점 조건부 UPDATE(`status!='reindexing'`, 컬렉션 행 잠금)로 봉인.
- **F3(수정됨, P1)**: `delete_document` 잠금 가드 누락 → `_reject_if_reindexing` 추가.
- **F6(수정됨, P2)**: 검색 잠금 체크를 질의 임베딩 *앞*으로 이동(fail-closed, 502→409 누수 봉인).
- **F2(경계)**: stale 잠금 회수는 단일 워커 가정. 멀티워커면 lease/heartbeat 필요(개인 도구=단일 워커).
- **F4(경계)**: update/delete_collection 잠금 가드는 point-in-time(TOCTOU 창). reindex끼리는 CAS 원자
  배타, 관리 CRUD-vs-reindex는 best-effort(드문 관리 액션).
- **F5(경계)**: 모델 probe 실패 시 차원 검증 통과 — create_collection과 동일 관대 정책. 실제 불일치는
  인제스트 가드2·health가 잡음.
- **F7(경계)**: 스왑 커밋과 이력 커밋 사이 크래시 시 이력 행 누락 가능(데이터 벡터는 원자·일관).
  런별 임베딩 모델은 EvalRun.env(240)에 별도 박제.

## OUT (명시 제외)
- **차원 변경**(1024↔768) — 전역 벡터 저장 구조 재설계. 별도 구조 스펙(deep-reasoner 선행).
- **멀티워커 stale 잠금 lease**(F2) · **관리 CRUD 원자 배타**(F4) — 분산/멀티프로세스 배포 시.
- **무중단 재인덱싱**(옛 인덱스 유지하며 새 인덱스 빌드 후 원자 교체) — 규모 커지면. 지금은
  사용자 요구대로 **배타 잠금**(다른 접근 차단)이 명시 선택.
- **다른 파서로 재파싱**(추출 로직 변경) — 원본 바이트는 저장하니 후속 가능. 이번은 청크 파라미터만.
- RAG 모델·청크 비교 격자(에이전트 141 미러) — 설정 A/B 자동 리포트. 후속 후보.

## 참고 자산
- [[gate-on-intent-value-not-mutable-baseline]] — 잠금 획득은 가변 status 대비 CAS(원자), 경합 회피.
- [[reload-reruns-migrations-mid-edit]] · [[hand-authored-migration-ids-collide-silently]] —
  마이그레이션 한 번에 완성·DB 측정·리비전 ID 충돌·단일 head 점검.
- [[whole-fix-over-minimal-patch]] — 개인용, 재인덱싱+재청킹+원본+잠금+이력+UI 한 단위로.
- [[installed-guard-isnt-covering-guard]] — 잠금은 "설치"가 아니라 모든 접근 경로(검색·인제스트·수정)
  를 덮어야 함(검사지점≠부수효과지점 틈 금지).
- 스펙 149(모델 불변)·198(청크 정책 불변 — 본 스펙이 재인덱싱 경로로 완화)·240(env 스냅샷)·020(차원 트랩).
