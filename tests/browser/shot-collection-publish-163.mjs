/* 스펙 163 브라우저 스모크 — RAG 컬렉션 "사용 공개" 토글 프론트엔드 배선 확인.
   목적: 콘솔 에러 없이 렌더되는지(런타임 에러 0) + 배지·토글이 나타나는지.
   (a) RAG 컬렉션 목록 진입
   (b) can_manage 컬렉션 행에 공개 토글(Switch) 렌더 확인
   (c) 공개된 컬렉션에 "공개" 배지(Tag) 렌더 확인(있으면)

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-collection-publish-163.mjs tests/browser/out-163 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/collection-publish-163'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()

const consoleErrors = []
page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(`${msg.text()} @ ${msg.location()?.url ?? ''}`)
})
page.on('pageerror', (err) => consoleErrors.push(String(err)))
page.on('requestfailed', (req) => consoleErrors.push(`requestfailed ${req.url()} ${req.failure()?.errorText}`))
page.on('response', (res) => {
  if (res.status() >= 400) consoleErrors.push(`http ${res.status()} ${res.url()}`)
})

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // (a) RAG 컬렉션 목록 진입
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}/1-collections-list.png`, fullPage: true })

  const rows = page.locator('table tbody tr')
  const rowCount = await rows.count()
  ok(rowCount > 0, `컬렉션 목록 행 렌더 (${rowCount}건)`)

  // (b) can_manage 컬렉션 행에 공개 토글(Switch) 렌더 확인 — 최소 1개는 있어야 정상(디폴트 seed는 소유자=관리자).
  const switches = page.locator('table tbody tr .ant-switch')
  const switchCount = await switches.count()
  ok(switchCount > 0, `공개 토글(Switch) 렌더 (${switchCount}건)`)

  // (c) "공개" 배지(Tag) — 아직 아무 것도 공개 안 했으면 0건일 수 있어 렌더 실패로 치지 않고 카운트만 보고.
  const publicTags = page.locator('table tbody tr').getByText('공개', { exact: true })
  const publicTagCount = await publicTags.count()
  console.log(`  info  "공개" 배지 현재 ${publicTagCount}건(초기 상태에 따라 0일 수 있음)`)

  // 실제 토글 동작 확인: 첫 Switch 클릭 → 목록 재조회 후 상태 반전 확인.
  if (switchCount > 0) {
    const firstSwitch = switches.first()
    const beforeChecked = await firstSwitch.getAttribute('aria-checked')
    await firstSwitch.click()
    await page.waitForTimeout(1000)
    const afterSwitch = page.locator('table tbody tr .ant-switch').first()
    const afterChecked = await afterSwitch.getAttribute('aria-checked')
    ok(beforeChecked !== afterChecked, `토글 클릭 후 상태 반전 (${beforeChecked} → ${afterChecked})`)
    await page.screenshot({ path: `${OUT}/2-after-toggle.png`, fullPage: true })
    // 원복(사이드이펙트 최소화).
    const revertSwitch = page.locator('table tbody tr .ant-switch').first()
    await revertSwitch.click()
    await page.waitForTimeout(1000)
  }

  // 로그인 전 401(요청 최초 인증 확인)·favicon 404·앱 전역 antd6 Alert/Drawer 폐기 경고는
  // 이 화면 밖에서도 항상 나는 기존 잡음(스펙 161과 동일 관례로 제외, 이번 diff는 Drawer 미변경 — grep 확인).
  const BASELINE_NOISE = [
    /favicon/i,
    /api\/users\/me/,
    /api\/auth\/login/,
    /antd: Alert.*deprecated/,
    /antd: Drawer.*deprecated/,
  ]
  const relevantErrors = consoleErrors.filter((e) => !BASELINE_NOISE.some((re) => re.test(e)))
  ok(relevantErrors.length === 0, `콘솔 에러(기존 잡음 제외) 0건 (실제 ${relevantErrors.length}건, 원본 ${consoleErrors.length}건)`)
  if (relevantErrors.length) relevantErrors.forEach((e) => console.log('  console error:', e))

  console.log('')
  if (fails.length) { console.log(`검증 실패 ${fails.length}건`); process.exitCode = 1 }
  else console.log('스펙 163 브라우저 스모크 — 전부 통과.')
} catch (e) {
  console.error('SHOT ERROR:', e.message)
  process.exitCode = 2
} finally {
  await browser.close()
}
