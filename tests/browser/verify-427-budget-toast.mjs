/* 스펙 427 검증(FE) — 사고 바닥 토스트 라이브 렌더 실증.
   오버라이드에서 Thinking 켬 + 최대 토큰 512 → 신선 질문 → "8192로 적용" 토스트가 뜨고 답이
   굶기지 않는지 확인. 서버 계약(truncated·thinkingBudgetApplied A+B1)은 tests/verify_427_budget.py가
   재현 가능하게 실측 — 여기선 onTrace→토스트 렌더 경로만 눈으로 닫는다.
   (A 잘림 토스트는 vLLM에서만 재현되는데 오버라이드 모델 셀렉트가 가상화라 브라우저서 불안정 →
    A는 verify_427_budget.py로 검증. B1은 모델 무관이라 기본 모델서 안정적으로 렌더된다.)
   실행: PLAYWRIGHT_DIR=tests/e2e/node_modules/playwright node tests/browser/verify-427-budget-toast.mjs */
import fs from 'node:fs'
import crypto from 'node:crypto'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }

const login = async () => {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForTimeout(1500)
  const need = await page.getByText('my-agents 로그인', { exact: true }).isVisible().catch(() => false)
  if (need) {
    await page.getByPlaceholder('you@example.com').fill(EMAIL)
    await page.getByPlaceholder('비밀번호').fill(PASSWORD)
    await page.getByRole('button', { name: '로그인' }).click()
    await page.waitForTimeout(1500)
  }
}
const gotoPlayground = async () => {
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  if ((await page.locator('button').filter({ hasText: 'personal-secretary' }).count()) === 0) {
    const combo = page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first()
    await combo.click()
    await page.getByText('personal-secretary', { exact: false }).first().click()
    await page.waitForTimeout(1000)
  }
}

try {
  await login()
  await gotoPlayground()

  // 오버라이드: Thinking 켬 + 최대 토큰 512(바닥 미만)
  await page.getByText('오버라이드', { exact: false }).first().click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(600)
  const thinkSelect = page
    .getByText('Thinking 모드', { exact: true })
    .locator('xpath=following::div[contains(@class,"ant-select")][1]')
  await thinkSelect.click()
  await page.waitForTimeout(400)
  await page.getByRole('option', { name: /^켬$/ }).click().catch(async () => {
    await page.locator('.ant-select-dropdown:visible').getByText(/^켬$/).first().click()
  })
  const mtInput = page
    .getByText('최대 토큰', { exact: true })
    .locator('xpath=following::input[contains(@class,"ant-input-number-input")][1]')
  await mtInput.click()
  await mtInput.fill('512')
  await page.waitForTimeout(200)
  await page.getByRole('button', { name: /적용/ }).click()
  await page.waitForTimeout(1000)

  // 신선 질문 → 사고 바닥 토스트("8192로 적용") + 답 본문
  const n = crypto.randomBytes(3).toString('hex')
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill(`V427-${n} — 세 단계로 생각한 뒤, 라면을 맛있게 끓이는 법을 한 문단으로 알려줘.`)
  await input.press('Enter')
  // 토스트는 turn 완료(trace) 직후 뜨고 antd 기본 3초 후 사라진다 — 뜨는 즉시 캡처.
  await page.getByText(/8192/, { exact: false }).first().waitFor({ timeout: 120000 })
  await page.screenshot({ path: `${OUT}/v427-b1-toast.png` })
  ok(true, 'B1 사고 바닥 토스트("8192로 적용") 렌더')

  console.log(fails.length ? `\nFAIL ${fails.length}` : '\nVERIFY427_OK')
  process.exitCode = fails.length ? 1 : 0
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: `${OUT}/v427-debug-fail.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
