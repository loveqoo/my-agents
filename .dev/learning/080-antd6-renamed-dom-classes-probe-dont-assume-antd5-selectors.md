# 080 — antd 6는 내부 DOM 클래스를 광범위 개명했다: Playwright 셀렉터는 antd5 이름을 가정 말고 probe로 실측

## 상황
브라우저 검증(Playwright)에서 antd 6 컴포넌트를 셀렉터로 잡을 때, antd5 시절 클래스 이름을
그대로 쓰면 **조용히 타임아웃/빈결과 → 거짓초록**(요소는 화면에 있는데 셀렉터가 못 잡음). 한 컴포넌트의
문제가 아니라 antd 6이 내부 클래스를 *여러 군데* 바꿔서, 매번 같은 함정을 다른 컴포넌트에서 다시 밟는다.

## 배운 것 (일반화)
- **확인된 개명(antd5 → antd6)**:
  - Modal 본문: `.ant-modal-content` → **`.ant-modal-container`** (스펙 075).
  - Select clickable(셀렉터 박스): `.ant-select-selector` → **`.ant-select-content`** (스펙 077).
  - *안 바뀐 것도 있다*: Drawer 루트 `.ant-drawer`, 옵션 `.ant-select-item-option`, 체크박스
    `.ant-checkbox-wrapper`/`.ant-checkbox-input`, Slider `.ant-slider`/`.ant-slider-disabled`,
    Switch `.ant-switch`는 그대로. → "다 바뀐다"도 "안 바뀐다"도 가정 금지, **개별 실측**.
- **증상으로 구분**: 클릭 대상이 안 잡히면 `locator.click: Timeout` + `waiting for locator(...)` —
  이건 "요소 없음"이 아니라 *셀렉터 클래스가 antd6에서 틀림*일 때가 잦다. getByText로 라벨은 잡히는데
  특정 `.ant-*` 클래스만 타임아웃이면 개명 의심.
- **probe로 실제 클래스를 찍는다**(추측 금지): 짧은 evaluate로 `[class*="drawer"]`·`[class*="ant-select"]`의
  `el.className`을 덤프해 *진짜 이름*을 본다. 한 번 찍으면 그 화면의 모든 셀렉터가 확정된다.
- **개명에 강한 셀렉터를 우선**: 클래스 대신 (1) `getByText`/`getByRole`로 라벨·역할, (2) `label`
  컨테이너로 스코프 후 그 안의 `.ant-select`(루트 클래스는 잘 안 바뀜) 클릭, (3) 폴백 체인
  (`.ant-select-item-option` 없으면 `.ant-select-item`). 깊은 내부 클래스(`-selector`/`-content`/`-container`)는
  버전 취약하니 최후로.

## 어떻게 적용하나
antd 6 화면을 Playwright로 검증하다 `.ant-*` 셀렉터가 타임아웃나면: ① getByText로 그 요소가
*렌더는 됐는지* 먼저 확인(렌더 O + 클래스 타임아웃 = 개명 의심), ② `[class*="..."]` evaluate로 실제
클래스 probe, ③ 라벨/역할 스코프 + 루트 클래스 + 폴백 체인으로 다시 짠다. 거짓초록 방지: 셀렉터가
0개 잡으면 *통과*가 아니라 *측정 실패*로 다룬다(스펙 075의 LABEL_HEIGHTS=[] 교훈).

## 근거
- 스펙 077: OverridePanel 페르소나 Select 검증 중 `.ant-drawer .ant-select-selector` 클릭이 30s
  타임아웃 → probe로 clickable이 `.ant-select-content`임을 확인(`.ant-select` 루트는 정상). 라벨 스코프
  `label:has-text("페르소나 블록에서 채우기") .ant-select`로 전환해 통과(systemPrompt 99→88자 채움 검증).
- 스펙 075: 모달 본문 `.ant-modal-content` 셀렉터가 빈결과 → `.ant-modal-container`로 정정.
- 관련: [[verify-ui-in-browser-proactively]](브라우저 선검증), [[probe-deeper-before-concluding]]("안 잡힘"을
  "없음"으로 단정 말고 probe), [[checkbox-with-description-stack-inside-label-not-as-flex-sibling]](075 — 같은 .ant-modal-container 함정).
