/* 스펙 032 검증 스크린샷 — 시스템 Chrome(channel:'chrome').
   로그인 → Playground 진입 → (1) 헤더에 userId 입력이 **없음**을 확인,
   (2) 채팅 1턴 → (3) "새 대화" 버튼 노출·동작을 캡처한다.
   mem0 user_id 축은 서버가 로그인 유저에서 도출하므로 수동 입력이 사라졌는지 눈으로 본다.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-playground-032.mjs /tmp/pg032 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/pg032'
// self-fixture(스펙 050 Phase 3): ADMIN_EMAIL 미지정이면 던짐용 super 즉석 시드 → 종료 시 자동 삭제.
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

try {
  // 로그인
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  log('LOGGED_IN')

  // Playground 진입 — '도구' 그룹의 'Playground' 메뉴.
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-playground.png` })

  // (1) 헤더에 userId 입력이 없어야 한다.
  const userIdInputs = await page.getByPlaceholder('userId').count()
  log('USERID_INPUT_COUNT=' + userIdInputs + ' (expect 0)')

  // (2) 메시지 입력 → 전송. @ant-design/x Sender는 textarea.
  const ta = page.locator('textarea').first()
  await ta.fill('안녕, 한 줄로 자기소개 해줘.')
  await ta.press('Enter')
  // 응답 스트리밍 대기 — 전송 후 어시스턴트 버블이 생길 시간.
  await page.waitForTimeout(6000)
  await page.screenshot({ path: `${OUT}-2-after-chat.png` })

  // (3) "새 대화" 버튼이 대화가 있을 때 노출되는지.
  const resetBtn = page.getByRole('button', { name: '새 대화' })
  const resetVisible = await resetBtn.count()
  log('RESET_BUTTON_COUNT=' + resetVisible + ' (expect >=1 after a turn)')
  if (resetVisible) {
    await resetBtn.first().click()
    await page.waitForTimeout(800)
    await page.screenshot({ path: `${OUT}-3-after-reset.png` })
    log('RESET_CLICKED')
  }

  log(userIdInputs === 0 ? 'NO_USERID_INPUT_OK' : 'USERID_INPUT_STILL_PRESENT_FAIL')
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
  else log('NO_CONSOLE_ERRORS')
} catch (e) {
  log('PG032_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png` }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
