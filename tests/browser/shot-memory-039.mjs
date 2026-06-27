/* 배치 뷰 — 유저 메모리 통합 패널 검증 스크린샷 (스펙 039) — 시스템 Chrome(channel:'chrome').
   admin(vite :5173) 로그인 후 '배치' 진입 → 메모리 통합 패널만 스코프해 임계치 설정 저장 +
   dry-run 트리거를 캡처한다. dry-run은 LLM 미리보기만(원본 무변형) — '지금 실행'(파괴적 교체)은
   절대 누르지 않는다(데이터 안전).

   실행: PLAYWRIGHT_DIR=<절대경로>/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-memory-039.mjs /tmp/mem039 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/mem039'
const EMAIL = process.env.ADMIN_EMAIL ?? 'verify032@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'Verify032!pw'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1100, height: 1100 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

try {
  // 1) 로그인
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  log('STEP1_LOGGED_IN')

  // 2) '배치' 메뉴 → 메모리 통합 패널로 스코프.
  await page.getByText('배치', { exact: true }).first().click()
  await page.getByText('유저 메모리 통합 (memory-consolidation)', { exact: false }).waitFor({ timeout: 10000 })
  const memPanel = page.locator('div:has(> h4:has-text("유저 메모리 통합"))')
  await memPanel.scrollIntoViewIfNeeded()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}-1-view.png`, fullPage: true })
  const thrLabel = await page.getByText('통합 임계치', { exact: false }).count()
  log('STEP2_MEMORY_PANEL threshold_label=' + thrLabel)

  // 3) 통합 임계치 입력 → 저장(설정 PATCH 왕복). 메모리 패널 안의 InputNumber만.
  const numInput = memPanel.locator('.ant-input-number-input').first()
  await numInput.click()
  await numInput.fill('5')
  await page.waitForTimeout(300)
  await memPanel.getByRole('button', { name: '설정 저장' }).click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-2-saved.png`, fullPage: true })
  log('STEP3_CONFIG_SAVED')

  // 4) Dry-run 트리거 → 토스트 + 이력 행(LLM 미리보기, 원본 무변형). '지금 실행'은 누르지 않음.
  await memPanel.getByRole('button', { name: 'Dry-run (미리보기)' }).click()
  await page.waitForTimeout(2500)
  await page.screenshot({ path: `${OUT}-3-dryrun.png`, fullPage: true })
  const dryTag = await page.getByText('dry-run', { exact: false }).count()
  log('STEP4_DRYRUN dry_run_markers=' + dryTag)

  log(errors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(errors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
  log('MEM039_SHOT_OK')
} catch (e) {
  log('MEM039_SHOT_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png`, fullPage: true }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
