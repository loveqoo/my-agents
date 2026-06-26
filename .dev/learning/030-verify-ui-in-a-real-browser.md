# 030 — UI 변경은 진짜 브라우저로 직접 확인한다 (사람 스샷 의존 X)

날짜: 2026-06-26
출처: 스펙 [028](../../docs/spec/028-playground-honest-model-badge.md) — 플레이그라운드 모델 배지
연결: [[019-playground-honest-model-badge]], [[probe-deeper-before-concluding]]

## 교훈

화면 변경의 검증을 **사용자 스샷에 의존하면 루프가 사람 속도로 느려지고**, 내가 "고쳤다"고
믿는 것과 화면에 실제로 뜨는 것이 어긋날 수 있다. 로컬에 **Playwright + 시스템 Chrome**만 있으면
브라우저 다운로드 없이 내가 직접 BEFORE/AFTER를 캡처해 **재현→수정→검증을 사람 없이 닫을 수 있다.**

이번엔 사용자가 보낸 스샷과 내가 찍은 BEFORE가 픽셀 수준으로 일치 → 버그 라이브 재현을
스스로 증명했고, AFTER로 수정을 스스로 증명했다.

## 적용 방법

- **수단**: 시스템 Chrome을 `channel:'chrome'`로 구동(브라우저 설치 불필요).
  ```js
  const _pw = await import(`${process.env.PLAYWRIGHT_DIR}/index.js`) // ESM은 NODE_PATH 무시 → 절대경로
  const chromium = _pw.chromium ?? _pw.default?.chromium
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 900, height: 1200 } })
  ```
  playwright 모듈이 프로젝트에 없어도 **npx 캐시**(`~/.npm/_npx/<hash>/node_modules/playwright`)를
  `PLAYWRIGHT_DIR`로 가리키면 package.json 오염 없이 재사용.
- **state 라우팅(URL 아님)이면** 딥링크 불가 → 메뉴 텍스트 클릭으로 진입하고
  `waitForTimeout`/셀렉터로 로드 대기 후 캡처. 드롭다운 등은 트리거를 클릭해 펼친 뒤 찍는다.
- 찍은 PNG는 **Read로 직접 보고**(이미지 인식) 의도대로인지 확인. 증거로 사용자에게도 보낸다.
- 재사용 하니스로 남긴다: `tests/browser/shot-playground.mjs`(스샷 경로 argv).
- **순서**: 사용자에게 스샷을 요청하기 전에 **내가 먼저 찍는다.** UI 수정/확인 작업의 기본기.
