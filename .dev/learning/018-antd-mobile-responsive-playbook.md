# 018 — antd 6 어드민 모바일 반응형 플레이북

연동: docs/spec/017-mobile-responsive-admin.md, [[008-porting-design-handoff-to-antd]],
[[016-verify-ui-before-test-guide]]

handoff 번들을 antd로 이식하면 인라인 스타일 + 고정 Sider라 모바일에서 깨진다.
재발 시 아래 패턴으로 빠르게 고친다.

## 반응형 신호
- `import { Grid } from 'antd'` → `const screens = Grid.useBreakpoint(); const isMobile = !screens.md`
  (md=768px). 추가 의존성 0.
- **함정**: `useBreakpoint()`는 첫 페인트에 `{}`(전부 undefined) 반환 →
  `isMobile = !undefined = true`로 데스크톱에서 1프레임 모바일 레이아웃 플래시.
  백드롭/오버레이를 첫 페인트에 그리면 눈에 띈다.
  **가드**: `const [mounted, setMounted] = useState(false); useEffect(()=>setMounted(true),[])`
  → `isMobile = mounted && !screens.md`. 마운트 전엔 데스크톱으로 간주.

## 고정 Sider → 모바일 오버레이
- Sider에 `collapsedWidth={isMobile ? 0 : 72}` + 모바일에서 `style={{position:'fixed',
  height:'100vh', left:0, top:0, zIndex:1100}}`. 닫히면 width 0 → 콘텐츠 풀폭 회수,
  열리면 fixed라 flow에서 빠져 본문을 안 민다.
  (antd `Sider.js`: user style 먼저 spread 후 `flex/width`를 덮음 → collapsed 시 `flex:0 0 0px`라
   in-flow footprint 0. 검증됨.)
- 백드롭: `isMobile && !collapsed`일 때만 `position:fixed; inset:0; zIndex:1099` div, onClick=닫기.
- 메뉴 `onSelect`에서 모바일이면 `setCollapsed(true)`로 자동 닫기.
- `breakpoint`+`useEffect([isMobile])`로 교차 시 자동 토글. 단 effect는 isMobile 변할 때만 →
  데스크톱 수동 토글을 안 덮어씀.

## 테이블 = 카드 변환 말고 가로 스크롤
- 커스텀 컬럼(width/align/render) 테이블은 카드 변환이 회귀 위험·공수 큼.
- `<table>`를 `<div style={{overflowX:'auto'}}>`로 감싸고 표에 `minWidth:'max-content'`.
  데스크톱은 `width:100%`가 지배(회귀 0), 모바일만 가로 스크롤. Panel `overflow:hidden`
  안쪽에 둬도 wrapper가 자체 스크롤 컨텍스트라 OK.

## 헤더/액션
- 제목+액션 한 줄 → 모바일 `flexDirection:'column'`로 스택(제목 줄바꿈 깨짐 방지).
- 액션 버튼 묶음 `inline-flex` → `flex + flexWrap:'wrap'`라야 좁은 폭에서 줄바꿈.
- 밀집 헤더(콤보+배지+버튼)는 모바일에서 버튼 라벨 제거(아이콘만, `title` 유지) + 부차 배지 숨김.

## 2단 그리드
- `'1fr 1fr'` → `'repeat(auto-fit, minmax(min(100%, Npx), 1fr)'`. 순수 CSS로 모바일 자동 1열.

## z-index 정렬 (이 코드베이스)
- Content 내부 Drawer 1000(로컬 stacking) < 모바일 Sider 백드롭 1099 < Sider 1100 < Playground
  인스펙터 전체화면 오버레이 1200.

## 검증
- Playwright 390x844 컨텍스트(`isMobile:true`)로 각 뷰 스크린샷 + `scrollWidth-clientWidth`로
  가로 overflow 측정(0이어야). 데스크톱 1280 회귀 스크린샷 대조. [[016-verify-ui-before-test-guide]]
