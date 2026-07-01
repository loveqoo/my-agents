/* sticky 액션 컬럼 검증(스펙 095) — 표가 실제로 넘치는 좁은 폭에서 에이전트 액션 버튼이
   뷰포트 안(우측 고정)에 있는지 수치+스크린샷으로 확인. login/nav는 measure-collections-table와 동일. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const VW = Number(process.env.VW ?? 880)
const OUT = process.argv[2] ?? `/tmp/sticky-agents-${VW}.png`

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 720 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  log('VIEWPORT=' + VW)
  const before = await page.evaluate((vw) => {
    const wrap = document.querySelector('table')?.parentElement
    const th = [...document.querySelectorAll('thead th')].pop()
    const r = th?.getBoundingClientRect()
    return { overflow: wrap ? wrap.scrollWidth - wrap.clientWidth : 0, actionRight: r ? Math.round(r.right) : null, inView: r ? r.right <= vw + 1 : null }
  }, VW)
  log('BEFORE_SCROLL ' + JSON.stringify(before))

  // 래퍼를 오른쪽 끝까지 스크롤 → sticky면 액션 th의 화면 우측 X가 그대로 뷰포트 안.
  await page.evaluate(() => { const w = document.querySelector('table')?.parentElement; if (w) w.scrollLeft = w.scrollWidth })
  await page.waitForTimeout(300)
  const after = await page.evaluate((vw) => {
    const th = [...document.querySelectorAll('thead th')].pop()
    const r = th?.getBoundingClientRect()
    // 첫 액션 버튼도 확인
    const firstRowBtns = document.querySelector('tbody tr')?.querySelectorAll('button')
    const b = firstRowBtns && firstRowBtns.length ? firstRowBtns[firstRowBtns.length - 1].getBoundingClientRect() : null
    return { actionRight: r ? Math.round(r.right) : null, thInView: r ? r.right <= vw + 1 : null, btnRight: b ? Math.round(b.right) : null, btnInView: b ? b.right <= vw + 1 : null }
  }, VW)
  log('AFTER_SCROLL_RIGHT ' + JSON.stringify(after))
  log(after.thInView && after.btnInView ? 'STICKY_OK' : 'STICKY_FAIL')
  await page.screenshot({ path: OUT, fullPage: false })
  log('SHOT ' + OUT)
} catch (e) {
  log('ERROR ' + (e?.message ?? e)); process.exitCode = 1
} finally { await browser.close() }
