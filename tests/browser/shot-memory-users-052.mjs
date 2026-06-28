/* 스펙 052 검증 — 유저 메모리 큐레이션 드롭다운이 raw UUID가 아니라 *이메일*로 식별되는지 캡처.
   메모리 메뉴 → 유저 메모리 탭 → 셀렉트를 열어 옵션 라벨(이메일)을 찍고, 한 유저를 골라
   패널 헤더가 이메일로 식별되는지(+ UUID 보조 병기) 본다.

   실행: PLAYWRIGHT_DIR=<npx>/node_modules/playwright node tests/browser/shot-memory-users-052.mjs [outPrefix] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const PREFIX = process.argv[2] ?? '/tmp/memory-users-052'
// self-fixture: ADMIN_EMAIL 미지정이면 던짐용 super 즉석 시드 → 종료 시 자동 삭제(스펙 050 Phase 3).
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(600)
  await page.getByRole('tab', { name: '유저 메모리' }).click()
  await page.waitForTimeout(500)

  // 셀렉트를 열어 옵션 라벨을 수집(이메일이 보여야 함 — raw UUID가 아니라).
  const sel = page.locator('.ant-select:visible').first()
  await sel.click()
  await page.waitForTimeout(500)
  const opts = await page.locator('.ant-select-item-option:visible').allInnerTexts()
  console.log('DROPDOWN_OPTIONS', JSON.stringify(opts))
  const hasEmail = opts.some((t) => t.includes('@'))
  // 옵션 라벨이 36자 UUID 통짜가 아니어야(이메일/이름) — 미등록 fallback "(미등록) <uuid>"는 허용.
  console.log('LABEL_HAS_EMAIL', hasEmail ? 'OK' : 'MISS')
  await page.screenshot({ path: `${PREFIX}-dropdown.png`, fullPage: true })
  console.log('SHOT_DROPDOWN', `${PREFIX}-dropdown.png`)

  // 이메일 옵션을 하나 골라 패널 헤더 식별 확인.
  const emailOpt = page.locator('.ant-select-item-option:visible', { hasText: '@' }).first()
  if (await emailOpt.count()) {
    await emailOpt.click()
    await page.waitForTimeout(1200)
    const header = await page.locator('text=에게만 회상됩니다').first().innerText().catch(() => '')
    console.log('PANEL_HEADER', JSON.stringify(header.slice(0, 120)))
    console.log('HEADER_HAS_EMAIL', header.includes('@') ? 'OK' : 'MISS')
    await page.screenshot({ path: `${PREFIX}-panel.png`, fullPage: true })
    console.log('SHOT_PANEL', `${PREFIX}-panel.png`)
  } else {
    console.log('NO_EMAIL_OPTION (등록 유저 세션 없음 — 라이브 데이터 의존)')
  }

  if (errors.length) console.log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 6)))
} catch (e) {
  console.log('SHOT_FAIL', e.message)
  await page.screenshot({ path: `${PREFIX}-fail.png`, fullPage: true }).catch(() => {})
} finally {
  await browser.close()
}
