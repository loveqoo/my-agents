/* 단건 응답 배지 e2e(스펙 408) — 사전 셋업(e2e-single-agent-408: streaming=false 모델)으로
   채팅 → 메시지 메타에 '단건' 태그. login/nav 패턴 공유.

   실행: PLAYWRIGHT_DIR=<pw> node tests/browser/verify-408-single-badge.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.argv[2] ?? '/tmp/verify-408-badge.png'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await ctx.newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  const pgMenu = page.getByText('Playground', { exact: true }).first()
  await page.waitForTimeout(1200)
  if (!(await pgMenu.isVisible().catch(() => false))) {
    await page.locator('button').first().click()
    await page.waitForTimeout(600)
  }
  await pgMenu.waitFor({ timeout: 10000 })
  await pgMenu.click()
  await page.waitForTimeout(2000)
  // 대상이 이미 기본 선택(목록 정렬)일 수 있음 — 헤더에 보이면 픽커 생략.
  const already = await page.getByText('e2e-single-agent-408', { exact: false }).first().isVisible().catch(() => false)
  if (!already) {
    console.log('step: 콤보 열기')
    await page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first().click()
    console.log('step: 에이전트 선택')
    await page.getByText('e2e-single-agent-408', { exact: false }).last().click()
    await page.waitForTimeout(1200)
  }
  console.log('step: 입력')
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill('안녕, 한 줄로 답해줘')
  await input.press('Enter')
  console.log('step: 배지 대기')
  await page.getByText('단건', { exact: true }).first().waitFor({ timeout: 60000 })
  ok(true, "① 메시지 메타에 '단건' 배지(비스트리밍 모델 표기)")
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT', OUT)
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
} finally {
  await browser.close()
}
console.log(fails.length ? `VERIFY408_BROWSER_FAIL(${fails.length})` : 'VERIFY408_BROWSER_OK')
process.exit(fails.length ? 1 : 0)
