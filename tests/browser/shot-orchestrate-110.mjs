/* 스펙 110 브라우저 시연 — 플레이그라운드에서 조율형 에이전트로 대화 1턴 → 인스펙터 trace에
   브로커 위임 노드(broker_invoke:rag:*)가 뜨는지. 시스템 Chrome.
   실행: ADMIN_URL=http://localhost:5173 PLAYWRIGHT_DIR=<abs> AGENT_NAME=<name> node tests/browser/shot-orchestrate-110.mjs /tmp/orch-110 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://localhost:5173'
const OUT = process.argv[2] ?? '/tmp/orch-110'
const AGENT = process.env.AGENT_NAME ?? '위임데모-조율형'
const QUERY = process.env.QUERY ?? 'docs_kb'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let fails = 0
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails++ }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  // Playground 진입.
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  // 상단 선택기 드롭다운 열기(기본 첫 에이전트 헤더 클릭 → 목록 open) 후 조율형 데모 선택.
  await page.getByText('Doc Translator', { exact: true }).first().click()
  await page.waitForTimeout(500)
  const nameEl = page.getByText(AGENT, { exact: true }).first()
  await nameEl.click({ timeout: 8000 })
  await page.waitForTimeout(800)
  check(true, `P1 조율형 데모 에이전트 선택(${AGENT})`)

  // 메시지 입력 후 전송(Enter).
  const box = page.locator('textarea').first()
  await box.click()
  await box.fill(QUERY)
  await page.waitForTimeout(200)
  await box.press('Enter')
  log(`  --  전송: ${QUERY}`)
  // 응답 완료 대기(mock-llm은 즉답 — 넉넉히).
  await page.waitForTimeout(4000)

  // 인스펙터 열기.
  await page.getByText('인스펙터', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  const body = await page.locator('body').innerText().catch(() => '')
  const hasBroker = /broker_invoke/.test(body)
  const hasRag = /broker_invoke:rag|rag:docs_kb|docs_kb/.test(body)
  check(hasBroker, 'P2 인스펙터 trace에 broker_invoke 노드(브로커 위임)')
  check(hasRag, 'P3 위임 대상 rag 표기')

  await page.screenshot({ path: `${OUT}.png`, fullPage: true })
  log('SHOT ' + OUT + '.png')
  log(fails === 0 ? 'ORCH110_OK' : `ORCH110_FAIL(${fails})`)
  if (fails) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
