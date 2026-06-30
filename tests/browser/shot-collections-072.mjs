/* RAG retrieval 시험 패널 검증 스크린샷 (스펙 072) — 시스템 Chrome.
   admin(vite :5173) 로그인 후 RAG 컬렉션 탭에서:
   (1) ready 컬렉션 행에 '검색' 버튼이 보이는지(스펙 072 신규 액션).
   (2) 검색 드로어를 열고 ready 컬렉션의 첫 청크 내용 일부를 질의 → 결과(유사도 카드)가 뜨는지.
   ready 컬렉션은 048 샘플(docs_kb)을 우선 사용하고, 없으면 목록의 첫 '준비됨' 행을 쓴다.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-collections-072.mjs /tmp/coll072 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/coll072'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 960 } })
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

  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-list.png`, fullPage: true })

  // ready 행 선택: docs_kb 우선, 없으면 '준비됨' Tag를 가진 첫 행.
  let row = page.locator('table tbody tr').filter({ hasText: 'docs_kb' }).first()
  if (!(await row.count())) row = page.locator('table tbody tr').filter({ hasText: '준비됨' }).first()
  const rowName = (await row.count()) ? (await row.locator('td').first().innerText().catch(() => '')) : '(none)'
  log('READY_ROW=' + JSON.stringify(rowName))

  const searchBtn = row.getByRole('button', { name: /검색/ }).first()
  const hasSearchBtn = await searchBtn.count()
  log('STEP1_SEARCH_BTN present=' + !!hasSearchBtn)
  if (hasSearchBtn) {
    await searchBtn.click()
    await page.waitForTimeout(800)
    await page.screenshot({ path: `${OUT}-2-drawer-open.png`, fullPage: true })

    // 질의 입력 → 검색. ready 컬렉션이면 어떤 의미 질의든 청크가 반환된다(floor 위 양수).
    const ta = page.locator('.ant-drawer textarea').first()
    await ta.fill('문서 내용에서 핵심을 알려줘')
    await page.locator('.ant-drawer').getByRole('button', { name: '검색' }).first().click()
    await page.waitForTimeout(2000)
    await page.screenshot({ path: `${OUT}-3-results.png`, fullPage: true })
    const drawerText = await page.locator('.ant-drawer').innerText().catch(() => '')
    const hitCount = (drawerText.match(/유사도 [\d.]+/g) || []).length
    const hasResultHdr = /결과 \d+건/.test(drawerText)
    log('STEP2_RESULTS hits=' + hitCount + ' header=' + hasResultHdr)
  }

  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
