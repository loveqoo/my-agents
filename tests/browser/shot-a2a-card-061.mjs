/* 스펙 061 D7 검증 샷 — 로컬(ui) 에이전트 노출 토글 ON 시 admin에 **실 A2A 카드 URL**이
   복사 가능하게 뜨는지 캡처·단언한다. 가짜 a2a:// 식별자가 아니라
   `http://…/agents/<pk>/.well-known/agent-card.json` 절대 URL이어야 한다.

   실행: PLAYWRIGHT_DIR=<…/node_modules/playwright> node tests/browser/shot-a2a-card-061.mjs [out.png] */
import { provisionSuper } from './_fixture.mjs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/a2a-card-061-shot.png'
const _fx = process.env.ADMIN_EMAIL ? { email: null, password: null } : provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 } })
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
  await page.waitForTimeout(1000)

  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(800)
  // ui 에이전트 상세 드로어 진입.
  await page.getByText('Research Assistant', { exact: true }).first().click()
  await page.waitForTimeout(1000)

  // "A2A로 공개" 토글이 OFF면 켠다(상세 드로어의 ExposeSwitch = role=switch).
  const sw = page.getByRole('switch').last()
  const onBefore = await sw.getAttribute('aria-checked')
  if (onBefore !== 'true') {
    await sw.click()
    await page.waitForTimeout(1200) // PUT expose + 재렌더
  }

  // 카드 URL 행이 뜰 때까지 — "A2A 카드" 라벨로 대기.
  const cardLabel = page.getByText('A2A 카드', { exact: true })
  await cardLabel.waitFor({ timeout: 8000 })
  await cardLabel.scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(400)
  await page.screenshot({ path: OUT, fullPage: true })

  // 단언: 실 카드 URL 표시 + 가짜 a2a:// 스킴 부재 + connect 안내·allowlist 힌트.
  const body = await page.locator('body').innerText().catch(() => '')
  const hasCardLabel = /A2A 카드/.test(body)
  const hasRealUrl = /\/agents\/[0-9a-f-]+\/\.well-known\/agent-card\.json/.test(body)
  const noFakeScheme = !/a2a:\/\/my-agents\./.test(body)
  const hasAllowlistHint = /A2A_ALLOWED_HOSTS=127\.0\.0\.1/.test(body)
  log('HAS_CARD_LABEL=' + hasCardLabel)
  log('HAS_REAL_CARD_URL=' + hasRealUrl)
  log('NO_FAKE_A2A_SCHEME=' + noFakeScheme)
  log('HAS_ALLOWLIST_HINT=' + hasAllowlistHint)
  const ok = hasCardLabel && hasRealUrl && noFakeScheme && hasAllowlistHint
  log(ok ? 'D7_OK' : 'D7_SUSPECT')
  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
} catch (e) {
  log('SHOT_FAIL', e.message)
} finally {
  await browser.close()
}
