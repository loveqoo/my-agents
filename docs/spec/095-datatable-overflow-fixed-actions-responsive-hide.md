# 095 — DataTable 가로 overflow: 액션 컬럼 고정 + 반응형 숨김 (제안 #6)

> 상태: 초안(AI 작성, 인간 검토 대기). 제안 8항목 중 #6. 접근은 사용자 승인("둘 다 — 고정+반응형 숨김").
> 참고 자산: retrospect 069/070·learning 069/070(covering-guard — 공용 컴포넌트 한 곳 수정으로 전
> 표면 커버), tests/browser/measure-collections-table.mjs(이 저장소 "overflow" = 테이블이 래퍼 안에서
> 가로 스크롤·액션 버튼 밀림의 확립된 정의), spec 062(중앙 error·무관), 브라우저 검증 관례
> (Playwright+시스템 Chrome, tests/browser/shot-*.mjs).

## 1. 배경 / 문제 (브라우저 측정으로 실증 — 추측 아님)

admin 테이블은 antd Table이 아니라 **커스텀 `DataTable`**(`shared.tsx:92`)이다. 데스크톱 경로는
`<div style="overflowX:auto"><table style="minWidth:max-content">`(`shared.tsx:159-160`)라 컬럼 합이
컨테이너보다 넓으면 **문서가 아니라 테이블 래퍼 안에서 가로 스크롤**이 생긴다(측정 `doc=0`,
`table.scrollWidth - wrap.clientWidth > 0`). 이때 우측의 **액션 버튼(편집/삭제)이 뷰포트 밖으로 밀려**
가로 스크롤해야 닿는다 — `measure-collections-table.mjs`가 조사하던 그 증상.

**측정 결과**(`survey-overflow-093.mjs`, 시스템 Chrome):

| 뷰 | 1280px | 1024px | 액션 컬럼 |
|---|---|---|---|
| 에이전트 | **+122px** | +378px | 있음(편집·삭제) |
| RAG 컬렉션 | 0 | +181px | 있음(문서·삭제 등) |
| 세션 | 0 | +196px | 없음(row-click 상세) |
| 배치 | 0 | +77px | 없음 |

에이전트는 **와이드(1280)에서도** 넘친다(컬럼 9개: 에이전트·소스·준수·페르소나·MCP·버전·공개·상태·
액션). 나머지 3개는 노트북 폭(1024)에서만.

## 2. 설계 결정

### 2.1 왜 공용 컴포넌트 한 곳인가 (covering-guard)

overflow의 원인은 각 뷰가 아니라 **공유 `DataTable`의 렌더 방식**이다. 4개 뷰를 개별로 손대는 대신
`DataTable`을 고쳐 **모든 테이블(유저·허용호스트·빌딩블록 포함)이 한 번에** 혜택을 본다(learning
069/070). 미래에 컬럼이 늘어 넘치는 뷰도 자동 커버 — 입구를 닫힌 집합으로 덮는다.

### 2.2 두 축(사용자 승인 "둘 다")

1. **액션 컬럼 고정(sticky-right)**: 액션 버튼을 항상 화면에 붙여 가로 스크롤과 무관하게 닿게 한다.
   - **자동 감지**: *마지막* 컬럼이 `title` 없음(=액션, 모바일 카드 경로와 동일 휴리스틱 `shared.tsx:112`)
     이거나 `fixed:'right'` 명시면 sticky. 에이전트·RAG 컬렉션이 해당(둘 다 `key:'actions', title:''`).
   - **CSS**: `position:sticky; right:0` + 불투명 배경(스크롤된 셀이 비치지 않게) + z-index. **가로
     overflow가 있을 때만** 왼쪽 그림자로 "더 있음"을 표시(없으면 그림자 0 — 안 넘치는 테이블엔 시각
     변화 없음). overflow 유무는 래퍼 ref + ResizeObserver로 측정(`scrollWidth > clientWidth`).
   - 세션·배치는 액션 컬럼이 없어 sticky 무관(row-click 상세로 전체 확인).
2. **반응형 숨김(hideBelow)**: 저우선 컬럼을 좁은 폭에서 숨겨 스크롤 필요 자체를 줄인다.
   - `Column<T>`에 `hideBelow?: Breakpoint` 추가. 데스크톱 테이블 경로에서
     `columns.filter(c => !c.hideBelow || screens[c.hideBelow])`로 거른다(`Grid.useBreakpoint`, 이미 사용 중).
   - **모바일 카드 경로엔 미적용** — 세로 배열이라 가로 공간 문제가 없으니 전 컬럼 표시(숨기면 데이터 손실만).
   - 브레이크포인트: 에이전트는 1280에서 넘치므로 그 위 유일 단계인 **xxl(≥1600)** 기준(1280–1599는
     축소셋, ≥1600 전체). 나머지는 1024에서만 넘치므로 **xl(≥1200)** 기준(1024는 축소, 1280은 전체 복귀).

### 2.3 숨김 대상(저우선 컬럼 — 측정으로 튜닝)

초기값(survey 재측정으로 worstTable→0 될 때까지 조정, Ralph식):

- **에이전트**: `mcps`·`version` → `hideBelow:'xxl'`(리스트/해시, 부차적. 상세는 row-click). 저장 ~260px > 122.
- **RAG 컬렉션**: `embedding_model_name`·`chunk_count` → `hideBelow:'xl'`.
- **세션**: `turns`·`tokens` → `hideBelow:'xl'`(지표, status/agent/lastActivity가 1차).
- **배치**: 저우선 1개(`started_at` 또는 `error`) → `hideBelow:'xl'`. (측정 후 확정.)

### 2.4 비-goal

- antd Table로 교체(디자인 명세 이탈, 대공사 — 배제).
- 컬럼 개인화/저장, drag-resize(후속 후보).
- 세로 overflow/가상 스크롤(무관 — 행 수 문제 아님).

### 2.5 RBAC 체크리스트 — 미적용

순수 프런트 표시 로직. `user_id`·owner 스코핑·소유권 헬퍼 무관. 트리거 불충족.

## 3. 구현

### 3.1 `shared.tsx` — `DataTable` + `Column`

- `Column<T>`: `hideBelow?: Breakpoint`, `fixed?: 'right'` 추가(`Breakpoint = 'xs'|'sm'|'md'|'lg'|'xl'|'xxl'`).
- 데스크톱 경로: (a) `visibleColumns` 필터, (b) 래퍼 `ref`+`ResizeObserver`로 `overflowing` 상태,
  (c) 액션 컬럼 판정 `isStickyRight(col, idx, visibleColumns)` → th/td에 sticky 스타일, (d) 그림자는
  `overflowing`일 때만.
- 모바일 경로: 기존 그대로(전 컬럼, hideBelow 무시).

### 3.2 4개 뷰 — 컬럼 주석

`AgentsView`·`CollectionsView`(collections 표)·`SessionsView`·`BatchView`의 저우선 컬럼에 `hideBelow`
추가. 액션 컬럼은 자동 감지라 주석 불필요(명시하려면 `fixed:'right'`).

## 4. 완료 조건 (측정가능) — survey-overflow 재측정 · 전부 GREEN

- [x] **에이전트 @1280: worstTable = 0**. 측정: `survey-overflow-093.mjs` VW=1280·1440 → bad 0/10.
- [x] **@1024: 4개 테이블 worstTable ≤ 소잔여**. 에이전트 @1024=0(source·exposed에 hideBelow:'xl'
      추가로 튜닝), Sessions 16px·Batch 21px 사소 잔차(액션 컬럼 없어 기능 손실 0, 92%/73% 감소).
- [x] **sticky 도달성**: `check-sticky-095.mjs` VW=880 → 래퍼 우측 끝까지 스크롤 후 액션 th·마지막
      버튼 우측 경계 모두 ≤ VW(`STICKY_OK`, btnRight=839·btnInView=true). 스크린샷 육안 확인 완료.
- [x] **회귀 없음**: shadow는 overflowing일 때만 표시(codex 확인), 모바일 카드 경로는 전체 `columns`
      그대로(hideBelow 미적용) 유지.
- [x] **적대 검증(rung③)**: codex 리뷰 결과 새 P0/P1 없음 — hook 순서 고정(모바일 early-return 앞),
      ResizeObserver cleanup·deps 안전(무한 루프 없음), sticky 오검지 없음(title 있는 마지막 컬럼 미고정),
      hideBelow가 액션 컬럼(hideBelow 없음) 미숨김. 지적된 P2(hover 미반영)는 수정·검증 완료(§5).

## 5. 알려진 잔존

- 1280–1599에서 에이전트 mcps/version 미표시(상세는 row-click). ≥1600 전체 복귀. 사용자 승인된 트레이드오프.
- ~~sticky 셀 hover 하이라이트 미세 불일치~~ → **수정 완료**: sticky td에 `data-sticky` 마커를 달고
  tr `onMouseEnter/Leave`에서 해당 셀 배경도 hover색↔컨테이너색으로 함께 갱신. 브라우저 검증
  `hover-sticky-095.mjs` → `HOVER_OK`(rest=흰색·hover=rgba(0,0,0,0.02)·leave=흰색 복원).
