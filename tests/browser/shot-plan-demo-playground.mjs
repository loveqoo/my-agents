/* 노드형 전환된 plan-execute-demo를 플레이그라운드 UI로 실행 + 인스펙터 캡처 (스펙 264). */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/plan-demo'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText('plan-execute-demo', { exact: false }).first().click()
  await page.waitForTimeout(600)

  const box = page.locator('textarea').first()
  await box.click()
  await box.fill('점진적 마이그레이션이 왜 안전한지 위키 근거로 한 문단 답해줘.')
  await page.waitForTimeout(200)
  await box.press('Enter')
  const chip = page.getByText(/\d+\s*mem/).last()
  await chip.waitFor({ state: 'visible', timeout: 180000 })
  await chip.click({ timeout: 8000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}-playground.png`, fullPage: false })
  log('shot: ' + OUT + '-playground.png')
  const body = await page.locator('#root').innerText().catch(() => '')
  log('NODES_VISIBLE=' + JSON.stringify(['계획', '실행'].map((n) => body.includes(n))))
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
