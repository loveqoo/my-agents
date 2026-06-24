# 008 — 어드민 콘솔 모바일 반응형 회고 (Sider 오버레이·표→카드·드로워 가로 스크롤)

날짜: 2026-06-24
브랜치: `feat/agent-service` (main 머지·push 금지 — 사용자가 직접 테스트)
지배 스펙: [017](../../docs/spec/017-mobile-responsive-admin.md)
이전 회고: [007-service-hardening-models-remote-env](./007-service-hardening-models-remote-env.md)

## 루프 개요
Tailscale로 실기기(아이폰 ~390px) 노출 후 어드민 UI가 깨지는 걸 발견 → 한 스펙(017) 안에서
3개 커밋으로 증분 수정. 매 증분이 **실기기 피드백 → 실측 → 수정 → 검증** 사이클이었다.

1. **1차 패스(`485ca0b`)** — Sider 모바일 오버레이(fixed + 백드롭 + collapsedWidth 0),
   헤더 검색창 숨김·패딩 축소, 2단 그리드(Overview/Agents) auto-fit, Playground 인스펙터
   전체화면, DebugChat 헤더 아이콘화. 이때 **표는 가로 스크롤 래퍼**로 결정.
2. **표→카드 + 드로워 버그(`62f1d68`)** — 사용자가 "가로 스크롤 엄청 불편" → 결정 번복,
   `DataTable` 모바일 카드화. 이어 "페이지 전체가 좌우로 움직임" 버그 → **닫힌 Drawer
   패널이 화면 밖에 머물며 Content 가로 스크롤을 만들던** 근본 원인 1개를 래퍼
   `overflow:hidden` 한 줄로 해결(antd Tabs 펼침 증상도 동시 해소).
3. **승인 그리드(`7ef504d`)** — 1차 패스에서 누락된 `ApprovalsView`의 `'1fr 1fr'`을 동일
   auto-fit 패턴으로 교체(텍스트가 한 글자씩 세로로 쪼개지던 증상 해소).

## 무엇이 잘됐나
- **실측으로 범인 확정(추측 금지 준수)**: "좌우로 움직임" 버그를 추측하지 않고 Playwright로
  `getBoundingClientRect().right > vw`인 요소를 폭 내림차순 덤프 → 닫힌 드로워 패널
  (`translateX(100%)`, left=390/right=780)을 정확히 짚음. 부모 체인까지 떠서 원인 1개로 수렴.
- **근본 원인 1개가 두 증상**: 드로워가 Content를 780px로 부풀려 (a) 직접 가로 스크롤,
  (b) antd Tabs가 그 폭으로 nav 측정해 펼침. 한 줄 수정으로 둘 다 해결 — 증상별로 땜질
  안 하고 공통 원인을 찾은 게 주효([[018]]).
- **타자 검증(서브에이전트)**: 카드 변환 diff를 비판 리뷰 → 액션 셀 버블링이 이미
  `stopPropagation`으로 막혀 P1 0건 확인. 자가검증이면 "버블링 위험"으로 오판했을 것.
- **데스크톱 회귀 0을 매번 실측**: 카드 분기는 `screens.md===false`로 격리, 데스크톱 표/드로워
  경로 무변경. 그리드도 `492px 492px 0px`(빈 트랙 collapse)로 2단 유지 확인.

## 무엇이 잘못됐나 / 배운 것
- **1차 검증 지표가 틀렸다(가장 큰 교훈)**: `documentElement.scrollWidth-clientWidth`로
  "가로 overflow 0"을 확신했지만, 오버플로가 `overflow:auto`인 `.ant-layout-content`
  *안에서* 흡수돼 documentElement엔 안 잡혔다. **스크롤 컨테이너가 따로면 그 요소 기준으로
  측정**해야 한다([[018]]에 명시). 사용자 실기기가 아니었으면 못 잡았을 버그.
- **결정 번복 비용**: 표를 "가로 스크롤이 표준 패턴"이라며 카드 변환을 회피했는데, 실기기에선
  강한 거부감. 데스크톱 직관으로 모바일 UX를 단정한 셈. 처음부터 카드로 갔어야.
- **1차 패스 누락**: 2단 그리드를 Overview/Agents만 고치고 ApprovalsView를 놓침. "같은 안티패턴
  전수 검색"을 했어야 — `gridTemplateColumns:'1fr 1fr'` grep 한 번이면 됐다.
- **JSX 주석 함정**: `return ( {/* */} <div> )`는 babel이 객체로 오해해 파싱 에러 → dev 서버가
  죽어 Playwright가 멈춤. 일반 `//` 주석을 `return` 위에 둘 것.
- **백그라운드 Bash + Playwright 충돌**: 잔여 chromium이 새 실행과 충돌("Target page closed").
  매 실행 전 `pkill -f scratch; pkill -f chromium` 선행이 필요했다.

## 다음에 다르게 / 추후
- **반응형 검증은 스크롤 컨테이너 단위로**: documentElement 측정만 믿지 말 것.
- **안티패턴은 전수 grep**: 한 곳을 고치면 동일 패턴을 저장소 전체에서 찾아 일괄 처리.
- **모바일 UX 결정은 실기기 우선**: 데스크톱 직관으로 단정하지 말고 가능하면 일찍 실기기 확인.
- 미완 추후: 세션/승인의 raw ISO 타임스탬프 가독성(현재 `2026-06-23T...+00:00` 그대로 노출),
  BlocksView 카테고리 탭의 `···` 더보기가 모바일에서 충분히 발견 가능한지 UX 점검.

## 관련 기록
- 학습 [[018-antd-mobile-responsive-playbook]] [[016-verify-ui-before-test-guide]]
  [[013-keep-the-step-header]] [[008-porting-design-handoff-to-antd]]
- 스펙 [017](../../docs/spec/017-mobile-responsive-admin.md)
