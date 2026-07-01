/* P2 회귀 검증: 좁은 폭(sticky 활성)에서 행 hover 시 sticky 액션 td 배경이 hover색으로 바뀌고
   이탈 시 컨테이너색으로 복원되는가. onRowClick 있는 Agents 뷰. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const VW = 880
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 720 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const read = () => page.evaluate(() => {
    const td = document.querySelector('tbody tr td[data-sticky]')
    return td ? getComputedStyle(td).backgroundColor : null
  })
  const rest = await read()
  await page.hover('tbody tr:first-child')
  await page.waitForTimeout(200)
  const hov = await read()
  await page.mouse.move(5, 5)
  await page.waitForTimeout(200)
  const left = await read()
  log('REST   ' + rest)
  log('HOVER  ' + hov)
  log('LEAVE  ' + left)
  const changed = rest && hov && rest !== hov
  const restored = hov && left && left === rest
  log(changed && restored ? 'HOVER_OK' : 'HOVER_FAIL')
} catch (e) { log('ERROR ' + (e?.message ?? e)); process.exitCode = 1 }
finally { await browser.close() }
