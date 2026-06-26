/* 세션 페이징 검증 스크린샷 (스펙 034) — 시스템 Chrome.
   admin(vite :5173) 로그인 후 세션 뷰에서:
   (1) 1페이지 + 페이지네이터 → (2) 2페이지 이동 → (3) 필터(라이브) 전환·page=1 리셋
   을 캡처한다. 서버 페이징(엔벌로프 {items,total,counts})이 페이지/필터 변경 시
   재조회되는지, 배지 카운트가 서버 counts에서 오는지 눈으로 확인.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-sessions-034.mjs /tmp/sess034 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/sess034'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
// /sessions 요청 URL을 기록 — 페이지/필터 변경 시 offset/status가 바뀌는지 증명.
const reqs = []
page.on('request', (r) => {
  const u = r.url()
  if (u.includes('/sessions?') || u.endsWith('/sessions')) reqs.push(u.split('/api')[1] ?? u)
})
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 세션 뷰
  await page.getByText('세션', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-page1.png`, fullPage: true })
  const pager = await page.locator('.ant-pagination').count()
  log('STEP1_SESSIONS pager=' + pager + ' reqs=' + JSON.stringify(reqs))

  // 2페이지로 이동(페이지네이터가 있으면)
  if (pager > 0) {
    const before = reqs.length
    // antd Pagination: title="2" 항목 클릭
    const p2 = page.locator('.ant-pagination-item-2 a')
    if (await p2.count()) {
      await p2.click()
    } else {
      await page.locator('.ant-pagination-next').click()
    }
    await page.waitForTimeout(1000)
    await page.screenshot({ path: `${OUT}-2-page2.png`, fullPage: true })
    log('STEP2_PAGE2 new_reqs=' + JSON.stringify(reqs.slice(before)))
  }

  // 필터 '라이브' 전환 → page=1 리셋·재조회
  const before2 = reqs.length
  await page.getByText('라이브', { exact: false }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-3-live.png`, fullPage: true })
  log('STEP3_FILTER_LIVE new_reqs=' + JSON.stringify(reqs.slice(before2)))

  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 5)))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
