/* 스펙 126 검증 — 메모리 조회(검색)가 **드로어 아님, 상세 페이지 인라인**(검색이 위·목록 아래).
   유저 선택 시 "회상 시험" 카드가 페이지 상단에 전체 폭으로 뜨고, 질의→조회하면 진단 패널(125)이
   그 자리에 지속 표시된다(드로어 없음·비밀 미노출). 시스템 Chrome.
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-memory-search-page-126.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/memory-search-page-126.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.getByText('유저 메모리', { exact: true }).first().click()
  await page.waitForTimeout(600)
  const combo = page.getByRole('combobox').first()
  await combo.click({ timeout: 8000 })
  await page.waitForTimeout(500)
  await page.locator('.ant-select-item-option').first().click({ timeout: 8000 })
  await page.waitForTimeout(800)

  // 드로어가 아니라 페이지 인라인 카드로 뜬다
  const noDrawer = (await page.locator('.ant-drawer-open').count()) === 0
  check(noDrawer, '드로어 없음(인라인 상세 페이지)')
  const card = page.locator('.ant-card').filter({ hasText: '회상 시험' }).first()
  check(await card.isVisible().catch(() => false), '"회상 시험" 카드가 페이지 상단에 인라인 표시')

  // 질의(유일 textarea) → 조회(카드 내 primary 버튼)
  await page.locator('textarea').first().fill('내가 선호하는 보고서 형식은?')
  await page.locator('.ant-card button.ant-btn-primary').first().click({ timeout: 8000 })
  await page.waitForTimeout(1800)

  const diag = page.getByText('진단', { exact: false }).first()
  check(await diag.isVisible().catch(() => false), '진단 패널이 페이지에 지속 표시')
  await diag.click().catch(() => {})
  await page.waitForTimeout(400)
  const body = await page.locator('#root').innerText().catch(() => '')
  check(/임베딩 모델|백엔드|스코프/.test(body), '진단 내용(임베딩 모델·백엔드·스코프) 노출')
  check(!/sk-[A-Za-z0-9]{6,}/.test(body), '비밀(sk-…) 화면 노출 없음')

  await page.screenshot({ path: OUT, fullPage: false })
  console.log('shot:', OUT)
} catch (e) {
  console.error('ERR', e.message)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
