/* 스펙 187 Phase 1 — shared.Drawer를 antd Drawer로 교체 후 앱 전역 드로어 사이트 회귀.
   컬렉션·세션·블록 뷰에서 행 클릭→antd 드로어(.ant-drawer-body) 열림·내용 렌더 확인. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1360, height: 960 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const log = (...a) => console.log(...a)
let fail = 0
const check = (ok, name) => { log(`${ok ? ' ok ' : 'FAIL'} ${name}`); if (!ok) fail++ }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 각 뷰: 메뉴 클릭 → 첫 행 클릭 → antd 드로어(.ant-drawer-body) 가시+내용 확인
  const sweep = async (menu, label, shot) => {
    await page.getByText(menu, { exact: true }).first().click()
    await page.waitForTimeout(1200)
    const rows = page.locator('table tbody tr')
    if (await rows.count() === 0) { log(` -- ${label}: 행 없음 — 스킵`); return }
    await rows.first().click()
    const body = page.locator('.ant-drawer-body')
    let ok = false, len = 0
    try {
      await body.waitFor({ state: 'visible', timeout: 3000 })
      len = ((await body.textContent()) ?? '').length
      ok = len > 20
    } catch { /* fail below */ }
    check(ok, `${label} antd 드로어 열림·내용 (${len}자)`)
    if (shot) await page.screenshot({ path: `${OUT}/drawer-187-${label}.png` })
    await page.keyboard.press('Escape')
    await page.waitForTimeout(600)
  }
  await sweep('RAG 컬렉션', 'collections', true)
  await sweep('세션', 'sessions', false)
  await sweep('빌딩 블록', 'blocks', false)

  check(pageErrors.length === 0, `Z1 pageerror 0 (실제: ${pageErrors.length})`)
  if (pageErrors.length) log('  pageerrors:', pageErrors.slice(0, 3))
  log(fail === 0 ? '\n✅ ALL PASS (ANTDDRAWER187_OK)' : `\n❌ ${fail} FAILED`)
} catch (e) {
  log('EXCEPTION:', String(e)); fail++
} finally {
  await browser.close()
}
process.exit(fail === 0 ? 0 : 1)
