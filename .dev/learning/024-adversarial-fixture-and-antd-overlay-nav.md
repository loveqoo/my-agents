# 024 — 적대적 픽스처로 "특정 콘텐츠 깨짐" 재현 + Playwright antd 오버레이 사이더 네비 함정

## 맥락
플레이그라운드 인스펙터 모바일 깨짐(spec 022). 시드 데이터로는 재현 안 됨 →
사용자 보고("특정 콘텐츠가 깨짐")와 내 측정이 어긋남.

## 배운 것 1 — 측정이 사용자 보고와 어긋나면, 입력을 의심하라 (not 사용자)
[[018]]의 모바일 오버플로 패턴(텍스트 노드 줄바꿈 보호 누락)은 **콘텐츠가 짧으면 잠복**한다.
시드는 전부 짧은 한국어/짧은 ID라 가로 오버플로가 안 났다. memory `probe-deeper-before-concluding`대로
"재현 안 됨"으로 단정하지 않고 **적대적 콘텐츠 픽스처**를 만들었다:
- 긴 URL(`...?q=` + x*140), 끊김 없는 토큰(`a`*80), 메모리 타입 태그 7개,
  긴 LangGraph 노드명, 긴 user_id/run_id(식별자 + `a`*80).
- 별도 Vite 엔트리(`inspector-fixture.html` → `_fixture.tsx`)로 컴포넌트만 격리 렌더,
  `position:fixed; inset:0`로 모바일 오버레이와 동일 조건.
→ 아이폰 320/390/430 전부에서 즉시 재현. **합성 입력으로 잠복 버그를 강제 표출**하는 게
시드 의존 측정보다 빠르고 결정적이었다.

## 배운 것 2 — antd Tag/flex 자식의 줄바꿈 보호 (017이 shared엔 넣었으나 playground는 누락)
- antd `Tag`는 기본 `white-space:nowrap` → 긴 단일 태그는 안 끊긴다. 래핑하려면
  태그 자체에 `whiteSpace:'normal'; height:'auto'; maxWidth:'100%'; overflowWrap:'anywhere'`.
- 태그 **행**은 `flexWrap:'wrap'`(+`rowGap`) 없으면 다수 태그가 가로로 줄줄이 넘침.
- flex 자식 안의 긴 토큰은 `minWidth:0` + `overflowWrap:'anywhere'`로 가둔다(min-width
  기본값 auto가 축소를 막아 넘침). 아이콘/시간 등 고정폭은 `flex:'none'`.
- `overflowWrap:'anywhere'` > `wordBreak:'break-all'`: 필요할 때만 끊어 가독성 우위(codex 확인).
- 이 패턴은 **너비 독립적** → 데스크톱 384px 패널의 동일 콘텐츠 깨짐도 함께 고쳐진다.

## 배운 것 3 — Playwright로 antd 오버레이 사이더 네비 (모바일 회귀 스윕)
모바일은 사이더가 `position:fixed` 오버레이라 햄버거로 열어야 한다. 두 함정:
1. **숨은 중복 `role=menuitem`**: `getByRole('menuitem', {name})`가 화면 밖 중복 항목을
   `.first()`로 잡아 `force` 클릭마저 타임아웃. → `locator('[role="menuitem"]:visible').filter({hasText: rx})`로
   **보이는 항목만** 스코프해야 안정적.
2. **antd 메뉴 트랜지션이 actionability 차단**: 육안으로 보이는데 click 타임아웃.
   → 슬라이드-인 대기 후 `click({force:true})`.
- 페이지 깨짐의 진짜 신호는 **`documentElement`/`.ant-layout-content`의 `scrollWidth-clientWidth`**
  (페이지 가로 스크롤). antd Tabs `.ant-tabs-nav-list`처럼 내부에서 클리핑되는 요소는
  요소 단위론 뷰포트를 넘겨도 페이지를 밀지 않는다(antd가 "더보기" 컨트롤 제공) → 통과로 판정.
  요소 단위 오버플로를 FAIL로 잡으면 오탐.

## 자산화
- 영구 회귀 가드: `tests/e2e/specs/mobile-overflow.spec.ts` + config `mobile` 프로젝트
  (아이폰 SE/13/14 Pro Max × 7뷰, chromium 고정·webkit 미설치 무관).
- 픽스처/스크래치는 검증 후 삭제(일회성). 관련 [[018]], spec 022.
