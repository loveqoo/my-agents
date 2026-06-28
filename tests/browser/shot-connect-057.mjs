/* 스펙 057 — 원격 에이전트 등록 단일화(connect) UI 검증, 시스템 Chrome.
   admin(vite :5173) 로그인 후 에이전트 뷰에서:
   (1) 헤더 액션에 '원격 에이전트 연결' 버튼 하나만 — 구 '원격 에이전트 등록'·'외부 A2A 등록' 없음.
   (2) 버튼 클릭 → 모달 '원격 에이전트 연결'(URL + 토큰 + [연결]).
   (3) SDK 카드 URL(/_remote/sdk, x-my-agents 확장)로 연결 → 토스트 'SDK 에이전트 (코드)'.
   (4) 외부 카드 URL(/_remote, 확장 없음)로 연결 → 토스트 '외부 A2A'.
   백엔드가 카드 fetch·provenance 자동분류. 생성 행은 별도 파이썬 스크립트로 정리(self-cleaning).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-connect-057.mjs /tmp/connect-057 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/connect-057'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

async function connectVia(url) {
  await page.getByRole('button', { name: '원격 에이전트 연결' }).click()
  await page.waitForTimeout(500)
  await page.getByPlaceholder(/agents.acme.example/).fill(url)
  await page.waitForTimeout(200)
  // 모달 푸터의 primary '연결' 버튼(아이콘 포함이라 role-name 매칭이 불안정 → 푸터 셀렉터로).
  await page.locator('.ant-modal-footer button.ant-btn-primary').click({ timeout: 8000 })
  await page.waitForTimeout(900) // 토스트는 2400ms 후 자동소멸 → 그 전에 읽도록 짧게 대기
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  // (1) 단일 버튼 — 구 버튼 없음.
  const headText = await page.locator('body').innerText().catch(() => '')
  const oneConnectBtn = /원격 에이전트 연결/.test(headText)
  const noOldRegister = !/원격 에이전트 등록/.test(headText)
  const noOldExternal = !/외부 A2A 등록/.test(headText)
  log('HEADER: connect_btn=' + oneConnectBtn + ' no_old_register=' + noOldRegister + ' no_old_external=' + noOldExternal)
  await page.screenshot({ path: `${OUT}-1-header.png`, fullPage: false })

  // (2) 모달 형태.
  await page.getByRole('button', { name: '원격 에이전트 연결' }).click()
  await page.waitForTimeout(600)
  const modalText = await page.locator('.ant-modal').innerText().catch(() => '')
  const modalOk = /원격 에이전트 연결/.test(modalText) && /에이전트 URL/.test(modalText) && /연결/.test(modalText)
  log('MODAL: shape_ok=' + modalOk)
  await page.screenshot({ path: `${OUT}-2-modal.png`, fullPage: false })
  // 모달 닫기(다음 단계서 다시 연다).
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(400)

  // (3) SDK 카드 → code 토스트.
  await connectVia('http://127.0.0.1:8000/_remote/sdk')
  let bodyText = await page.locator('body').innerText().catch(() => '')
  const codeToast = /연결됨/.test(bodyText) && /SDK 에이전트 \(코드\)/.test(bodyText)
  log('CONNECT_SDK: code_toast=' + codeToast)
  await page.screenshot({ path: `${OUT}-3-sdk-toast.png`, fullPage: false })
  await page.waitForTimeout(2200) // 토스트 사라질 때까지

  // (4) 외부 카드 → external 토스트.
  await connectVia('http://127.0.0.1:8000/_remote')
  bodyText = await page.locator('body').innerText().catch(() => '')
  const extToast = /연결됨/.test(bodyText) && /외부 A2A/.test(bodyText)
  log('CONNECT_EXT: ext_toast=' + extToast)
  await page.screenshot({ path: `${OUT}-4-ext-toast.png`, fullPage: false })

  const ok = oneConnectBtn && noOldRegister && noOldExternal && modalOk && codeToast && extToast
  log(ok ? 'CONNECT_057_OK' : 'CONNECT_057_SUSPECT')
  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
