/* 허용 호스트 뷰 — 스펙 064 신규 SSRF allowlist 관리 화면 검증 (시스템 Chrome, channel:'chrome').
   admin 로그인 → '허용 호스트' 진입 → 목록(env 부트스트랩 시드) 캡처 → 임시 host 추가(성공 토스트)
   → 와일드카드 거부(422 detail 노출) 캡처 → 추가한 임시 host 삭제(Popconfirm)로 DB 순변화 0.

   계정: ADMIN_EMAIL 미지정이면 _fixture.mjs가 던짐용 super를 즉석 시드하고 종료 시 자동 삭제한다.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-allowed-hosts-064.mjs /tmp/allowed064 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/allowed064'
const TEST_HOST = '10.88.0.5' // 사설 IP — UI로 추가했다 삭제(정리)
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1100, height: 1400 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  log('STEP1_LOGGED_IN')

  // 사이드바 '허용 호스트' 메뉴 진입.
  await page.getByText('허용 호스트', { exact: true }).first().click()
  await page.getByText('호스트 추가', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByText('등록된 허용 호스트', { exact: true }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}-1-list.png`, fullPage: true })
  log('STEP2_VIEW_LOADED')

  // 임시 host 추가 → 성공.
  const hostInput = page.getByPlaceholder('예: 127.0.0.1 또는 agent.internal')
  await hostInput.fill(TEST_HOST)
  await page.getByRole('button', { name: '추가', exact: true }).click()
  await page.getByText(TEST_HOST, { exact: false }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}-2-added.png`, fullPage: true })
  log('STEP3_HOST_ADDED')

  // 와일드카드 거부 — 422 detail이 토스트/에러로 노출되는지.
  await hostInput.fill('*.evil.com')
  await page.getByRole('button', { name: '추가', exact: true }).click()
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${OUT}-3-reject.png`, fullPage: true })
  log('STEP4_WILDCARD_REJECTED')

  // 정리: 추가한 임시 host 삭제(Popconfirm '삭제' 확인).
  const row = page.locator('tr', { hasText: TEST_HOST }).first()
  await row.getByRole('button', { name: '삭제' }).click()
  await page.getByRole('button', { name: '삭제' }).last().click() // Popconfirm 확인
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${OUT}-4-after-delete.png`, fullPage: true })
  log('STEP5_HOST_DELETED')

  log(errors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(errors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
  log('ALLOWED064_SHOT_OK')
} catch (e) {
  log('ALLOWED064_SHOT_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png`, fullPage: true }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
  if (_fx) _fx.teardown?.() // exit 핸들러가 어차피 보장하나 명시적으로도 정리
}
