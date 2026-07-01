/* 스펙 106 검증 — 에이전트 편집 폼에 실행 방식(impl) + 능력(capabilities) 노출. 시스템 Chrome.
   admin(vite :5173) 로그인 → '새 에이전트' → impl Select·능력 피커 렌더·토글·오케스트레이터 힌트 확인.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright node tests/browser/shot-caps-impl-106.mjs /tmp/caps-106 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/caps-106'
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
  // 모달 스크롤로 새 필드까지 노출.
  await page.getByText('실행 방식 (impl)', { exact: true }).scrollIntoViewIfNeeded()
  await page.waitForTimeout(200)

  // 1) impl Select 존재 + 능력 섹션 존재.
  check(await page.getByText('실행 방식 (impl)', { exact: true }).count() > 0, 'H1 실행 방식(impl) 필드 렌더')
  check(await page.getByText(/능력 \(브로커 위임\)/).count() > 0, 'H1 능력(브로커 위임) 필드 렌더')
  check(await page.getByText('오케스트레이터 실행 방식에서 사용됨').count() > 0,
    'H2 기본 impl일 때 능력에 "오케스트레이터에서 사용됨" 힌트')

  // 2) 능력 그룹·고정 항목(내 기억 읽기/쓰기) 노출.
  check(await modal.getByText(/내 기억 읽기 \(memory:user\)/).count() > 0, 'H3 memory:user 후보 노출')
  check(await modal.getByText(/내 기억 쓰기 \(memwrite:user\)/).count() > 0, 'H3 memwrite:user 후보 노출(저장 시 승인)')
  check(await modal.getByText('내 기억', { exact: true }).count() > 0, 'H3 kind별 그룹 제목(내 기억)')

  // 3) impl Select 열어 orchestrate 옵션 확인(레지스트리 일치).
  const implLabel = page.getByText('실행 방식 (impl)', { exact: true })
  const implSelect = implLabel.locator('xpath=following-sibling::*[contains(@class,"ant-select")][1]')
  await implSelect.click()
  await page.waitForTimeout(300)
  // 옵션은 포털 렌더(.ant-select-dropdown) — 텍스트로 확인.
  check(await page.getByText('오케스트레이터 · 첫 매치 위임').count() > 0, 'H4 impl 옵션에 orchestrate(첫 매치)')
  check(await page.getByText('오케스트레이터 · 랭킹 조합').count() > 0, 'H4 impl 옵션에 orchestrate_ranked(랭킹)')
  await page.getByText('오케스트레이터 · 첫 매치 위임').click()
  await page.waitForTimeout(300)

  // 4) 오케스트레이터 선택 시 힌트 Tag 사라짐.
  check(await page.getByText('오케스트레이터 실행 방식에서 사용됨').count() === 0,
    'H5 오케스트레이터 선택 → 힌트 Tag 사라짐')

  // 5) memory:user·memwrite:user 체크 → checked 반영.
  const memRead = modal.locator('.ant-checkbox-wrapper', { hasText: 'memory:user' }).first()
  await memRead.click()
  await page.waitForTimeout(150)
  const memReadBox = memRead.locator('.ant-checkbox-input')
  check(await memReadBox.isChecked(), 'H6 memory:user 체크 반영')

  await page.getByText('실행 방식 (impl)', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${OUT}.png`, fullPage: true })
  log('SHOT ' + OUT + '.png')
  log(fails === 0 ? 'VERIFY106_OK' : `VERIFY106_FAIL(${fails})`)
  if (fails) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
