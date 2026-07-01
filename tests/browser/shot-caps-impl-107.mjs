/* 스펙 107 검증 — 능력 피커 UX: 오케스트레이터 조건부 + 종류별 접이식. 시스템 Chrome.
   기본 impl→능력 칸 없음, orchestrate 선택→접이식 등장(기본 접힘), 펼침·카운트 배지 확인.

   실행: ADMIN_URL=http://localhost:5173 PLAYWRIGHT_DIR=<abs> node tests/browser/shot-caps-impl-107.mjs /tmp/caps-107 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://localhost:5173'
const OUT = process.argv[2] ?? '/tmp/caps-107'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let fails = 0
const check = (cond, msg) => { log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails++ }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(800)
  const modal = page.locator('.ant-modal-container')

  // 1) 기본 impl(=기본 UI 에이전트)일 때 능력 칸 자체가 없음 — 폼 단순.
  await page.getByText('실행 방식 (impl)', { exact: true }).scrollIntoViewIfNeeded()
  check(await modal.getByText(/능력 \(브로커 위임\)/).count() === 0, 'H1 기본 impl → 능력 칸 없음(단순)')

  // 2) impl=orchestrate 선택 → 능력 칸 등장.
  const implSelect = page.getByText('실행 방식 (impl)', { exact: true })
    .locator('xpath=following-sibling::*[contains(@class,"ant-select")][1]')
  await implSelect.click()
  await page.waitForTimeout(300)
  await page.getByText('오케스트레이터 · 첫 매치 위임').click()
  await page.waitForTimeout(300)
  check(await modal.getByText(/능력 \(브로커 위임\)/).count() > 0, 'H2 orchestrate 선택 → 능력 칸 등장')

  // 3) 종류별 접이식 패널 존재 + 기본 접힘(체크박스 숨김).
  await modal.getByText(/능력 \(브로커 위임\)/).scrollIntoViewIfNeeded()
  await page.waitForTimeout(200)
  const panels = modal.locator('.ant-collapse-item')
  check(await panels.count() >= 4, `H3 종류 패널 4개 이상(=${await panels.count()})`)
  const activeAtStart = await modal.locator('.ant-collapse-item-active').count()
  check(activeAtStart === 0, 'H3 기본 전부 접힘(선택 0이라 펼친 패널 없음)')

  // 4) 패널 헤더에 카운트 배지(선택/전체).
  check(await modal.locator('.ant-collapse-header').filter({ hasText: '내 기억' }).getByText('0/2').count() > 0,
    'H4 헤더 카운트 배지(내 기억 0/2)')

  // 5) 내 기억 패널 펼치면 체크박스 노출.
  await modal.locator('.ant-collapse-header').filter({ hasText: '내 기억' }).click()
  await page.waitForTimeout(300)
  check(await modal.getByText(/내 기억 읽기 \(memory:user\)/).count() > 0, 'H5 펼침 → memory:user 체크박스 노출')

  // 6) memory:user 체크 → 헤더 카운트 1/2 반영.
  await modal.locator('label.ant-checkbox-wrapper', { hasText: '내 기억 읽기' }).locator('input').check()
  await page.waitForTimeout(250)
  check(await modal.locator('.ant-collapse-header').filter({ hasText: '내 기억' }).getByText('1/2').count() > 0,
    'H6 체크 → 헤더 카운트 1/2')

  await modal.getByText(/능력 \(브로커 위임\)/).scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${OUT}.png`, fullPage: true })
  log('SHOT ' + OUT + '.png')
  log(fails === 0 ? 'VERIFY107_OK' : `VERIFY107_FAIL(${fails})`)
  if (fails) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
