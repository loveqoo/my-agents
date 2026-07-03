/* 스펙 161 브라우저 스모크 — 페르소나 스냅샷 동기화 UI 배선 확인.
   목적: 콘솔 에러 없이 렌더되는지(런타임 에러 0) + 섹션이 깨지지 않고 나타나는지.
   (a) 에이전트 목록 → 첫 에이전트 상세 드로어 열기
   (b) 재료(Blocks) → 페르소나 탭 → 첫 페르소나 → 편집 드로어 열기

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-persona-sync-161.mjs tests/browser/out-161 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/persona-sync-161'
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

  // (a) 에이전트 목록 → 페르소나를 가진(ui/code) 에이전트 상세 드로어 — 첫 행은 external(A2A)일 수 있어
  // 페르소나 필드 자체가 없다(설계상 정상). ReadonlyConfig(code)·AgentDetail(ui) 둘 다 확인.
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  const codeRow = page.locator('table tbody tr', { hasText: 'Doc Translator' }).first()
  await codeRow.waitFor({ timeout: 10000 })
  await codeRow.click()
  await page.waitForTimeout(1000)
  ok(await page.getByText('페르소나', { exact: true }).first().isVisible().catch(() => false), '에이전트 상세(code): 페르소나 항목 렌더')
  await page.screenshot({ path: `${OUT}/1a-agent-detail-code.png`, fullPage: true })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  const uiRow = page.locator('table tbody tr', { hasText: 'Personal Secretary' }).first()
  await uiRow.waitFor({ timeout: 10000 })
  await uiRow.click()
  await page.waitForTimeout(1000)
  ok(await page.getByText('페르소나', { exact: true }).first().isVisible().catch(() => false), '에이전트 상세(ui): 페르소나 항목 렌더')
  await page.screenshot({ path: `${OUT}/1b-agent-detail-ui.png`, fullPage: true })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  // (b) 재료(Blocks) → 페르소나 탭 → 첫 항목 → 편집 드로어
  await page.getByText('빌딩 블록', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.getByRole('tab', { name: /페르소나/ }).click()
  await page.waitForTimeout(800)
  const firstPersonaRow = page.locator('table tbody tr').first()
  await firstPersonaRow.waitFor({ timeout: 10000 })
  await firstPersonaRow.click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: '편집' }).click()
  await page.waitForTimeout(1000)
  ok(await page.getByText('이 페르소나를 쓰는 에이전트', { exact: true }).isVisible().catch(() => false), '페르소나 편집: 사용 에이전트 섹션 렌더')
  const applyBtn = page.getByRole('button', { name: '선택 에이전트에 반영' })
  ok(await applyBtn.count() > 0, '페르소나 편집: 반영 버튼 렌더')
  await page.getByText('이 페르소나를 쓰는 에이전트', { exact: true }).scrollIntoViewIfNeeded()
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${OUT}/2-persona-edit.png`, fullPage: true })

  // 로그인 전 401(요청 최초 인증 확인)·favicon 404·앱 전역 antd6 Alert `message`→`title` 폐기 경고는
  // 이 화면 밖에서도 항상 나는 기존 잡음(스펙 161과 무관, git stash 대조로 확인) — 제외하고 판정.
  const BASELINE_NOISE = [
    /favicon/i,
    /api\/users\/me/,
    /api\/auth\/login/,
    /antd: Alert.*deprecated/,
  ]
  const relevantErrors = consoleErrors.filter((e) => !BASELINE_NOISE.some((re) => re.test(e)))
  ok(relevantErrors.length === 0, `콘솔 에러(기존 잡음 제외) 0건 (실제 ${relevantErrors.length}건, 원본 ${consoleErrors.length}건)`)
  if (relevantErrors.length) relevantErrors.forEach((e) => console.log('  console error:', e))

  console.log('')
  if (fails.length) { console.log(`검증 실패 ${fails.length}건`); process.exitCode = 1 }
  else console.log('스펙 161 브라우저 스모크 — 전부 통과.')
} catch (e) {
  console.error('SHOT ERROR:', e.message)
  process.exitCode = 2
} finally {
  await browser.close()
}
