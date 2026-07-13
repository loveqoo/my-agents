# 332 — 엔티티 문서 편집 개방(331 확장, 행 단위 부분 재임베딩)

## 배경 / 요구 (사용자, 2026-07-14)

스펙 331이 편집에서 제외한 엔티티 컬렉션도 수정 가능하게 — 검토 결과 방안 B(331 에디터 개방) 채택.
엔티티는 1행=1청크라 부분 재임베딩이 정확히 행 단위로 떨어져 오히려 문서형보다 유리.

## 설계 (331 기계 재사용 — 차이만)

- **_doc_editable**: 엔티티 제외 판정 제거(비PDF·blob 보존만 유지). 원본 미보존 엔티티(movies-demo
  등 스펙 312 이전 적재)는 기존 사유로 자연 차단 — 로더 재실행이 처방.
- **PUT 재청킹 분기**: `kind=entity`면 `_parse_entity_rows`(기존 헬퍼 — **기본 행 계약**(JSON 객체·
  metadata 객체·data 비어있지 않음)은 항상 fail-closed·위반 행 번호 400, `entity_schema`는 컬렉션에
  **있으면** 추가 검증 — 업로드 입구와 동일 계약) → chunks=행 텍스트·metas=행 metadata. 문서형은
  기존 chunk_text.
  부분 재임베딩(text→벡터 맵)은 공통 — **텍스트 동일·meta만 변경된 행은 재임베딩 0으로 meta 갱신**.
- **프론트**: 편집 버튼의 엔티티 제외 해제. 에디터에 컬렉션 kind 전달 — 엔티티면 푸터 힌트를
  "행(JSONL) 단위 — 바뀐 행만 다시 임베딩. 원본은 파이프라인 재업로드가 덮을 수 있습니다(임시 교정)"
  로(정직 경계 명시). `.jsonl`은 language-data에 없어 json 하이라이트로 수동 매핑.

## 검증 (완료 조건)

1. verify_332(일회용 DB): E1 엔티티 GET editable=true·JSONL 왕복 · E2 **행 단위 부분 재임베딩**
   (1행 data 변경+1행 meta만 변경+1행 유지 → 임베딩 호출=변경 1행만, meta-only 행은 벡터 재사용+
   DB meta 갱신, 통계 reembedded 1·reused 2) · E3 스키마 위반 행 → 400+행 번호 · E4 blob 없는
   엔티티 → editable=false(원본 미보존) · E5 meta 동반 검색(수정 행 meta가 hit에 반영) ·
   E6 집계=실측.
2. 브라우저 e2e: 엔티티 문서 편집 버튼 활성 → 에디터 저장 → 토스트(기능 왕복).
3. lint/mypy/tsc/build 클린 · verify_331 무회귀 · codex 적대 P1/P2 0.

## OUT

- 행 단위 편집 UI(방안 A — B 사용 불편이 실증되면) · 파이프라인 역동기화(편집→SQL 반영은 없음,
  임시 교정 명시로 갈음) · entity_schema 없는 컬렉션의 형식 자유 편집 제한 강화.

## 결과 (2026-07-14 실행)

- 설계대로 — 백엔드는 사실상 분기 2곳(+_doc_editable 개방), 331 기계 전부 재사용. meta만 바꾼
  행은 재임베딩 0으로 meta 갱신이 실측 확인(E2c).
- codex 적대 P1 0·P2 1·P3 2 반영:
  - **P2 NaN/Infinity 우회**: `json.loads`가 비표준 상수를 기본 허용 → 파서 통과 후 JSONB insert
    500. `parse_constant` 거부 훅으로 **업로드·편집 두 입구 공통 봉인**(149부터 있던 기존 구멍을
    이번 리뷰가 표면화 — 행 번호 400 계약 유지, verify_149 31/31 무회귀).
  - **P3 kind 화이트리스트**: DB 컬럼 String(20)이라 미지/레거시 kind가 문서형 청킹 경로로 흘러들
    수 있어 document/entity 명시 화이트리스트 fail-closed.
  - **P3 스키마 문구 정직화**: 기본 행 계약(객체·metadata·data)은 항상, entity_schema는 있으면 —
    로 스펙 문구 분리(스키마 없는 컬렉션의 자유 편집은 의도).
- 검증: VERIFY332_OK 14/14(행 단위 부분 재임베딩 캡처 실증·NaN 400·미지 kind 차단) ·
  VERIFY332_UI_OK(엔티티 탭→편집 버튼 활성→JSONL 편집→"재임베딩 1·재사용 1" 토스트→blob 교체) ·
  331 19/19·149 31/31 무회귀 · lint/mypy/tsc/build 클린.
