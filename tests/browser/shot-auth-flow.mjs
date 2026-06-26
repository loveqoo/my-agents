/* 인증 플로우 검증 스크린샷 (스펙 031) — 시스템 Chrome(channel:'chrome').
   admin(vite :5173)을 띄워: (1) 로그인 화면 → (2) 로그인 후 셸 →
   (3) 유저 관리 뷰를 순서대로 캡처한다. 세션 쿠키가 same-origin /api 프록시로 동행하는지,
   401→로그인 화면 게이트가 도는지를 눈으로 확인한다.

   실행: PLAYWRIGHT_DIR=<절대경로>/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-auth-flow.mjs /tmp/auth */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/auth'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

const log = (...a) => console.log(...a)

try {
  // 1) 로그인 화면 — 미인증이라 AuthGate가 LoginScreen을 띄워야 한다.
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.screenshot({ path: `${OUT}-1-login.png` })
  log('STEP1_LOGIN_SHOWN')

  // 2) 로그인 → 셸
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  // 셸의 사이드 메뉴(에이전트)가 뜰 때까지.
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}-2-shell.png` })
  log('STEP2_LOGGED_IN')

  // 3) 유저 관리 뷰 — 슈퍼유저 메뉴 '유저' 클릭.
  await page.getByText('유저', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-3-users.png` })
  // 시드 admin 행이 보이는지 텍스트로 확인.
  const adminRow = await page.getByText(EMAIL, { exact: false }).count()
  log('STEP3_USERS_VIEW admin_rows=' + adminRow)

  // 4) 로그아웃 → 다시 로그인 화면(게이트).
  await page.locator('.ant-layout-sider').getByText(EMAIL, { exact: false }).first().click().catch(() => {})
  await page.waitForTimeout(400)
  await page.getByText('로그아웃', { exact: true }).first().click().catch(() => {})
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.screenshot({ path: `${OUT}-4-logout.png` })
  log('STEP4_LOGOUT_BACK_TO_LOGIN')

  log('AUTH_FLOW_OK')
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
  else log('NO_CONSOLE_ERRORS')
} catch (e) {
  log('AUTH_FLOW_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png` }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
