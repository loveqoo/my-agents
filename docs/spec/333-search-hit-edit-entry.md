# 333 — 검색 시험 히트에서 즉시 편집 진입

> **⚠️ 스펙 338(2026-07-14)에서 롤백** — 사용자 결정: 편집 진입은 문서 목록으로 일원화. 이 문서는 이력 보존용.


## 배경 / 요구 (사용자, 2026-07-14)

"검색 테스트 결과에서 버튼을 눌러 즉시 수정할 수 있으면?" — 수만 줄 논의(방안 A 검토)에서 나온
정밀 진입의 실현. 동선: 검색해 보니 이 청크/행이 이상함 → 히트 카드의 편집 버튼 → 에디터가 **그
지점으로 스크롤·선택된 채** 열림 → 교정 → 저장(변경분만 재임베딩, 331/332 승계).

## 설계

- **백엔드**: 검색 코어(`runtime.search_collections`) 히트에 `document_id` 동반(SELECT에 이미
  Document join 존재 — 컬럼 하나 추가). `SearchHit` 스키마에 `document_id: UUID | None`(additive —
  인-챗 도구·trace는 키 선택식이라 무영향).
- **패널 주입점**: `RetrievalTestPanel`에 `hitAction?: (hit) => ReactNode`(히트 카드 헤더 우측).
  메모리 어댑터는 미전달(무변경) — 컬렉션 어댑터만 편집 버튼 렌더(can_manage && document_id).
- **에디터 정밀 진입**: `DocumentEditorModal`에 `locate?: string` — 로드 완료 후 본문에서 히트
  텍스트의 첫 위치를 찾아 **선택+가운데 스크롤**. 엔티티는 JSONL 라인 안에서 이스케이프될 수
  있어 후보 2개(원문·JSON 이스케이프 내부형)로 탐색, 못 찾으면 그냥 열림(우아한 강등).
- SearchDrawer가 히트에서 합성 doc({id, filename})으로 모달을 연다 — 모달은 GET content로
  editable을 서버 판정(PDF 등은 사유 Alert, 기존 경로 그대로).

## 검증 (완료 조건)

1. verify_333: 검색 히트에 document_id 동반(실제 문서와 일치) + 그 id로 content GET 왕복
   (히트→편집의 API 사슬) · 문서형/엔티티 양쪽.
2. 브라우저 e2e: 검색 시험 → 히트 편집 버튼 → 에디터 열림(해당 텍스트 선택됨) → 교정 저장 →
   재검색에 반영(기능 왕복).
3. lint/mypy/tsc/build 클린 · verify_331/332 무회귀 · codex 적대 P1/P2 0.

## OUT

- 저장 후 검색 결과 자동 재실행(수동 재검색으로 확인 — 패널 상태 소유권 침범 없이) ·
  메모리(회상 시험) 히트 편집(도메인이 다름 — mem0 수정은 별 경로) · 행 단위 편집 폼(방안 A 본체).

## 결과 (2026-07-14 실행)

- 설계대로 — 히트 카드 편집 버튼 → 에디터가 **히트 텍스트 선택+스크롤된 채** 열림(e2e에서
  선택 상태를 window.getSelection으로 실측). 저장 후 "다시 검색해 반영 확인" 안내.
- codex 적대 P1 0·P2 1·P3 1 반영: ①locate 후보에 ASCII \\uXXXX 전량 이스케이프형 추가
  (ensure_ascii 계열 파이프라인 JSONL은 비ASCII가 escape로 저장 — 원문/JSON내부형만으론 못 찾음)
  ②비노출 핀 H5 — document_id는 시험 엔드포인트에만 있고 인-챗 trace(_hits_detail 화이트리스트)
  에는 없음을 명시 단언. 권한은 설계상 닫힘 확인(검색=공용이지만 content GET/PUT은 may_manage
  404-fold — id를 알아도 비소유는 접근 불가, verify_331 G8 핀).
- 검증: VERIFY333_OK 6/6(히트→편집 API 사슬 문서형/엔티티+additive+비노출 핀) ·
  VERIFY333_UI_OK(검색→선택된 채 편집→저장 토스트→재검색 반영 관통) · 331 19/19·332 14/14
  무회귀 · lint/mypy/tsc/build 클린.
