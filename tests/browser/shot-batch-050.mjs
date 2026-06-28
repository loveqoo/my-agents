/* 배치 뷰 — 스펙 050 신규 패널 검증 스크린샷 (시스템 Chrome, channel:'chrome').
   admin 로그인 → '배치' 진입 → A2A 정크 정리·테스트 유저 정리 두 신규 패널을 캡처한다.
   유저 패널은 이메일 패턴 입력 + dry-run까지(실삭제 '지금 실행'은 절대 누르지 않음 — 데이터 안전).

   계정: ADMIN_EMAIL 미지정이면 _fixture.mjs가 던짐용 super를 즉석 시드하고 종료 시 자동 삭제한다
   (050 Phase 3 self-fixture — 영속 verify032 의존 제거). 환경변수로 명시하면 그 계정을 쓴다.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-batch-050.mjs /tmp/batch050 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/batch050'
// self-fixture(스펙 050 Phase 3): ADMIN_EMAIL 미지정이면 던짐용 super 즉석 시드 → 종료 시 자동 삭제.
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

  await page.getByText('배치', { exact: true }).first().click()
  await page.getByText('A2A 정크 정리 (a2a-cleanup)', { exact: false }).waitFor({ timeout: 10000 })
  await page.getByText('테스트 유저 정리 (user-cleanup)', { exact: false }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)
  log('STEP2_NEW_PANELS_PRESENT')

  // 두 신규 패널이 보이도록 하단으로 스크롤 후 전체 캡처.
  await page.getByText('테스트 유저 정리 (user-cleanup)', { exact: false }).scrollIntoViewIfNeeded()
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}-1-panels.png`, fullPage: true })

  // A2A 정리 dry-run(설정 없음) — 토스트 + 이력 행.
  const a2aDry = page
    .locator('div')
    .filter({ hasText: /^A2A 정크 정리/ })
    .getByRole('button', { name: 'Dry-run (미리보기)' })
    .first()
  await a2aDry.click().catch(() => {})
  await page.waitForTimeout(1200)
  log('STEP3_A2A_DRYRUN')

  // 유저 정리 — 이메일 패턴 입력 + dry-run.
  const patternInput = page.getByPlaceholder('예: verify%@example.com  (비우면 비활성)')
  await patternInput.fill('verify%@example.com')
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${OUT}-2-user-pattern.png`, fullPage: true })
  log('STEP4_USER_PATTERN_FILLED')

  log(errors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(errors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
  log('BATCH050_SHOT_OK')
} catch (e) {
  log('BATCH050_SHOT_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png`, fullPage: true }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
