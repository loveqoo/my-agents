/* 일회용 측정 — RAG 컬렉션 테이블의 실제 폭/오버플로우를 잰다(추측 금지).
   table.scrollWidth vs clientWidth(=가로 스크롤 유무), 각 th 폭, 액션 셀 버튼들이
   뷰포트 안에 있는지. 실행은 shot-collections-072.mjs와 동일 환경. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const VW = Number(process.env.VW ?? 1280)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 960 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  log('VIEWPORT=' + VW)
  const m = await page.evaluate(() => {
    const table = document.querySelector('table')
    const wrap = table?.parentElement // overflowX:auto div
    const ths = [...(table?.querySelectorAll('thead th') || [])].map((th) => ({
      t: th.textContent.trim() || '(actions)',
      w: Math.round(th.getBoundingClientRect().width),
    }))
    return {
      tableScrollW: table?.scrollWidth,
      wrapClientW: wrap?.clientWidth,
      overflow: table ? table.scrollWidth - wrap.clientWidth : null,
      ths,
    }
  })
  log('TABLE_SCROLL_W=' + m.tableScrollW + ' WRAP_CLIENT_W=' + m.wrapClientW + ' OVERFLOW=' + m.overflow)
  log('COLS=' + JSON.stringify(m.ths))

  // ready 행의 액션 버튼들이 뷰포트 안에 보이는지
  let row = page.locator('table tbody tr').filter({ hasText: 'docs_kb' }).first()
  if (!(await row.count())) row = page.locator('table tbody tr').filter({ hasText: '준비됨' }).first()
  const btns = row.locator('button')
  const n = await btns.count()
  const vis = []
  for (let i = 0; i < n; i++) {
    const b = btns.nth(i)
    const box = await b.boundingBox()
    const label = (await b.innerText().catch(() => '')) || '(icon)'
    vis.push({ label: label.trim() || '(icon)', right: box ? Math.round(box.x + box.width) : null, inView: box ? box.x + box.width <= VW : false })
  }
  log('ACTION_BTNS=' + JSON.stringify(vis))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
