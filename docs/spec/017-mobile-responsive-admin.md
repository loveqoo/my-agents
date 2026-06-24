# 017 — 어드민 콘솔 모바일 반응형 (풀 패스)

상태: **완료**
날짜: 2026-06-24
브랜치: `feat/agent-service` — main 머지 금지
연동: [[005-tailscale-expose-dev-servers]](.dev/troubleshooting), AdminShell.tsx, shared.tsx, Playground.tsx
범위 합의: 사용자 = "풀 패스 — 모바일 완성도"

## 배경
Tailscale 노출 후 모바일(~390px)에서 UI가 깨짐. Playwright 스크린샷(390x844)으로
재현·확정 — 콘솔 에러 0(순수 레이아웃). 단일 1차 원인 + 4개 부수 표면.

## 진단 (스크린샷·소스로 확정)
1. **AdminShell `<Sider width={232}>`에 `breakpoint` 없음** → 모바일에서도 항상 펼쳐져
   콘텐츠를 ~158px로 짜부라뜨림 (1차 원인).
2. **Header 검색창 `width:220` 고정** → 좁은 화면에서 넘침.
3. **`Page` `padding:24` 고정** → 모바일에서 가용폭 추가 잠식.
4. **`DataTable`**: `Panel{overflow:hidden}` 안의 `<table>` 헤더 `whiteSpace:nowrap`
   → 좁은 화면에서 잘리거나 셀 넘침.
5. **2단 그리드** `gridTemplateColumns:'1fr 1fr'` (OverviewView:103, AgentsView:152)
   → 모바일에서 안 접힘.
6. **Playground 2단 flex**(DebugChat + Inspector 나란히) → 모바일에서 양쪽 짜부라짐.

## 설계 결정
- **반응형 신호**: antd `Grid.useBreakpoint()` 사용(추가 의존성 0). `isMobile = !screens.md`(<768px).
- **테이블**: 카드 변환이 아니라 **가로 스크롤 래퍼**(`overflow-x:auto`)로 처리.
  사유 — 4개 테이블이 각자 커스텀 컬럼(width·align·render)을 가져 카드 변환은 회귀 위험·공수 큼.
  모바일 테이블 가로 스크롤은 표준 패턴이며 데이터 손실 없음.
- **Sider**: 모바일에서 **오버레이**(position:fixed + 백드롭, 기본 닫힘, 메뉴 선택 시 자동 닫힘),
  `collapsedWidth={0}`로 닫히면 콘텐츠가 풀폭 회수. 데스크톱은 기존 동작 유지.

## 변경 계획
### A. `AdminShell.tsx`
- `Grid.useBreakpoint()`로 `isMobile` 산출. 모바일이면 `collapsed` 기본 true.
- Sider: 모바일에서 `position:fixed; height:100vh; zIndex:1100` + 백드롭 div(클릭 시 닫힘),
  `collapsedWidth={0}`. 데스크톱은 현행.
- 메뉴 `onSelect`: 모바일이면 선택 후 `setCollapsed(true)`.
- Header: 모바일에서 검색창(`width:220`) 숨김, 햄버거·제목 유지. `padding` 모바일 축소.

### B. `shared.tsx`
- `Page`: `padding` 모바일 16(데스크톱 24 유지). `useBreakpoint`.
- `DataTable`: `<table>`를 `<div style={{overflowX:'auto'}}>`로 감싸 가로 스크롤.

### C. 2단 그리드
- OverviewView:103, AgentsView:152의 `'1fr 1fr'` →
  `repeat(auto-fit, minmax(min(100%, 280px), 1fr))` (순수 CSS, 모바일 자동 1열).

### D. `Playground.tsx`
- `useBreakpoint`로 모바일 판정. 모바일: DebugChat 풀폭, Inspector는 **전체화면 오버레이**
  (기존 `onClose` 재사용, position:fixed + zIndex). 데스크톱은 기존 2단 유지.

## 검증 (완료 조건)
- [x] `tsc --noEmit` 통과.
- [x] Playwright 390x844: agents/blocks/models/sessions/overview/playground 7화면 —
      콘솔에러 0, 가로 overflow 0px(테이블 내부 스크롤 별개), 제목/카드/버튼 안 깨짐. 스크린샷 대조.
- [x] 데스크톱(1280) 회귀 없음 — 스크린샷 동일.
- [x] 타자 검증: 서브에이전트 비판 리뷰 — P1 0건. antd `Sider.js` 소스까지 읽어
      `max-content`·fixed-Sider flex갭 안전 확인. P2: `useBreakpoint()` 첫 페인트 `{}` 플래시
      → mounted 가드로 데스크톱 백드롭 플래시 제거.

## 추가 변경 (실측 반영)
- `Page` 헤더: 모바일 세로 스택(제목 위, 액션 아래) — 제목 줄바꿈 깨짐 해소.
- AgentsView/BlocksView 액션 `inline-flex`→`flex+flexWrap` — 좁은 폭에서 버튼 줄바꿈.
- DebugChat 헤더: 모바일 아이콘만 버튼 + A2A 배지 숨김 — 한 줄 겹침 해소.
- AdminShell: `mounted` 가드로 첫 페인트 플래시 방지.

## 비고
- 기능·데이터·라우팅 무변경. 순수 레이아웃/CSS.
- main 머지·push 금지(사용자 직접 브랜치 테스트).
