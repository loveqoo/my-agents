# 074 — RAG 컬렉션 액션 가시성: 검색 버튼 승격 + 테이블 오버플로우 해소 (072 후속)

## 배경

스펙 072가 CollectionsView 액션 컬럼에 "검색" 버튼을 추가했으나, 사용자가 **검색 버튼을
못 찾았다**("검색버튼이 안 보여서 몰랐어"). 브라우저 캡처(1280px)로 원인을 측정:

1. **테이블 가로 오버플로우** — DataTable(shared.tsx)은 데스크탑에서 `minWidth: 'max-content'`
   + 래퍼 `overflowX: 'auto'`다. 컬럼 max-content 합이 컨테이너를 넘으면 가장 오른쪽 **액션
   컬럼이 가로 스크롤 뒤로 잘려**, 검색·점검·삭제가 화면 밖으로 사라진다(스크롤 안 하면 안 보임).
   - 실측: TABLE_SCROLL_W=1067 vs WRAP_CLIENT_W=998 → **69px 넘침**. 삭제 아이콘 right=1308 > 1280.
   - **범인 컬럼은 액션이 아니라 이름 컬럼**(392px = maxWidth 360 + 패딩 32). 첫 추측(액션 290)이
     아니라 *측정*이 진짜 범인을 가리켰다.
2. **검색 버튼 저발견성** — 검색이 `type="text" size="small"`(배경·테두리 없는 작은 텍스트)로
   4버튼 중 셋째라 눈에 안 띔.

## 목표 (완료 조건 — 측정 가능)

1280px에서 컬럼 max-content 합 ≤ 컨테이너(OVERFLOW=0) → 모든 액션 버튼이 뷰포트 안(`inView=true`).
검색 버튼은 primary로 승격해 한눈에 보인다. 검색 드로어 기능·모바일 카드 모드 무회귀.

## 조치 (CollectionsView.tsx)

- **검색 = primary 버튼**으로 승격(파란 채움, 라벨 유지). disabled(미-ready)는 흐릿 유지(의도).
- **문서·점검·삭제 = 아이콘 + Tooltip**으로 압축(라벨 제거) → 액션 컬럼 폭 290→170, `inline-flex gap`.
- **이름 컬럼 description 줄임표**(`whiteSpace:nowrap; overflow:hidden; textOverflow:ellipsis`) +
  **`maxWidth: 260`** — 긴 설명이 테이블 max-content를 키워 우측 액션을 밀어내던 *진짜 범인*을 억제.
  (360→260으로 셀 ~100px 절약 → 1280 OVERFLOW 69→0.)

## 검증 (브라우저 실측 — verify-ui-in-browser)

- `tests/browser/measure-collections-table.mjs`(신규 진단 도구) — table.scrollWidth vs
  wrap.clientWidth로 오버플로우, 각 th 폭, 액션 버튼 boundingBox `inView` 측정.
  - 1280: OVERFLOW 0, 액션 4개 전부 inView. 1440: OVERFLOW 0.
- `tests/browser/shot-collections-072.mjs`(VW 환경변수 추가) — 데스크탑/모바일 캡처.
  검색 드로어 hits=3(무회귀). 모바일 390 카드 모드: 검색 primary 또렷, 회귀 없음.
- 타입체크(tsc --noEmit) 통과.

## RBAC 체크리스트 적용 여부

**관련 없음** — 순수 표현(presentational) 변경. user_id/소유권 컬럼·소유 헬퍼 무관, 입구/권한 불변.

## 완료 체크
- [x] 검색 primary 승격, 나머지 아이콘+Tooltip, 액션 폭 290→170
- [x] 이름 description 줄임표 + maxWidth 260 → 1280 OVERFLOW 0(측정)
- [x] 데스크탑 1280/1440·모바일 390 캡처로 가시성 확인, 검색 드로어 무회귀
- [x] 타입체크 통과
