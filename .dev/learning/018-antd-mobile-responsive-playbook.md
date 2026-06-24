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

## 테이블 = 모바일에선 카드 (가로 스크롤 금지)
- **처음엔 가로 스크롤 래퍼로 갔다가 사용자 피드백으로 카드로 뒤집음.**
  모바일 가로 스크롤은 "엄청 불편" — 목록 전체를 보려면 좌우로 밀어야 함. 실기기에서 강한 거부감.
- 패턴: `DataTable`에서 `screens.md === false`면 표 대신 각 행을 `Panel` 카드로.
  컬럼 분해 — `const [head, ...rest] = columns`. **1열=헤더**(fontSize 15),
  `rest.filter(c=>c.title)`=라벨:값 행(라벨 minWidth 80, 값 `flexWrap:wrap minWidth:0`),
  `rest.filter(c=>!c.title)`=액션(편집/삭제, 하단 우측 정렬).
- 전제 2개(현 뷰에선 성립, 새 컬럼셋 추가 시 주의): **1열은 비대화형 표시 셀**,
  **falsy title = 액션 컬럼**. 액션 셀은 이미 `e.stopPropagation()`을 호출하므로
  카드 전체 onClick(onRowClick) 위에 얹혀도 버블링 안전.
- `Desc`(드로워 key/value)도 모바일은 `flexDirection:column`으로 라벨을 윗줄에 쌓아 값 폭 확보.

## 함정: 화면 밖 Drawer 패널이 가로 스크롤을 만든다 (★ 진짜 범인)
- 증상: 모바일에서 좌우로 밀면 페이지 바디 전체가 움직이고 우측에 빈 공간. 여러 뷰에서 동시 발생.
- **`document.documentElement.scrollWidth-clientWidth` 측정은 0으로 나와 못 잡는다** —
  오버플로가 `overflow:auto`인 `.ant-layout-content` *안에서* 흡수되기 때문. 반드시
  **Content 요소의 `scrollWidth-clientWidth`로 측정**하고, `getBoundingClientRect().right > vw`인
  요소를 폭 내림차순으로 덤프해 범인을 찾을 것.
- 원인: 커스텀 Drawer 패널이 닫힘 시 `transform:translateX(100%)`로 자기 폭만큼 화면 밖 오른쪽에
  머무는데(`position:absolute; right:0`), 부모 래퍼(`position:absolute; inset:0`)에 클리핑이 없어
  Content가 그 패널을 가로 스크롤 영역으로 노출. (열림 시 `translateX(0)`이라 평소엔 안 보임.)
- **수정: 드로워 래퍼에 `overflow:hidden` 한 줄.** 닫힌 패널 클리핑, 열린 패널은 경계 안이라 무해.
- 2차 효과: Content가 부풀면(예: 780px) **antd `Tabs`가 그 폭으로 nav를 측정해 모든 탭을 한 줄로
  펼친다**(`···` 더보기 드롭다운이 안 뜸). Content를 정상 폭으로 되돌리면 Tabs가 자동으로
  overflow 드롭다운을 표시 → Tabs는 따로 손댈 필요 없었음. **한 근본 원인이 두 증상을 만들었다.**

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
