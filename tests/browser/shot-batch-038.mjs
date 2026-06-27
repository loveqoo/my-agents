/* 배치 뷰 검증 스크린샷 (스펙 038) — 시스템 Chrome(channel:'chrome').
   admin(vite :5173) 로그인 후 슈퍼유저 메뉴 '배치' 진입 → 보존정리 설정 패널 +
   dry-run 트리거 + 실행 이력 테이블을 캡처한다. 세션 쿠키가 same-origin /api 프록시로
   동행해 GET /admin/batch/config·runs가 200을 반환하는지 눈으로 확인.

   주의: '지금 실행'(실삭제)은 누르지 않는다 — dry-run만 트리거(데이터 안전).

   실행: PLAYWRIGHT_DIR=<절대경로>/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-batch-038.mjs /tmp/batch */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/batch'
const EMAIL = process.env.ADMIN_EMAIL ?? 'verify032@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'Verify032!pw'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1100, height: 980 } })
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

  // 2) '배치' 메뉴 클릭 → 설정 패널 + 이력 테이블 로드.
  await page.getByText('배치', { exact: true }).first().click()
  await page.getByText('세션 보존정리 (session-cleanup)', { exact: false }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-1-view.png`, fullPage: true })
  const panelOk = await page.getByText('보존일수', { exact: false }).count()
  log('STEP2_BATCH_VIEW retention_label=' + panelOk)

  // 3) 보존일수 입력 → 저장(설정 PATCH 왕복).
  const numInput = page.locator('.ant-input-number-input').first()
  await numInput.click()
  await numInput.fill('30')
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '설정 저장' }).click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-2-saved.png`, fullPage: true })
  log('STEP3_CONFIG_SAVED')

  // 4) Dry-run 트리거 → 토스트 + 이력에 dry-run 행 추가(실삭제 없음).
  await page.getByRole('button', { name: 'Dry-run (미리보기)' }).click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}-3-dryrun.png`, fullPage: true })
  const dryTag = await page.getByText('dry-run', { exact: false }).count()
  log('STEP4_DRYRUN dry_run_markers=' + dryTag)

  log(errors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(errors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
  log('BATCH_SHOT_OK')
} catch (e) {
  log('BATCH_SHOT_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png`, fullPage: true }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
