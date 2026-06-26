/* Provider 엔티티 검증 스크린샷 (스펙 035) — 시스템 Chrome.
   admin(vite :5173) 로그인 후:
   (1) 프로바이더 탭 목록(시드 2개 + 마스킹 키 + 모델 수)
   (2) 프로바이더 등록 모달(이름/프로토콜/Base URL/키 + 연결 테스트)
   (3) 모델 탭 목록(프로바이더 컬럼 + 상속 base_url, 키 컬럼 없음)
   (4) 모델 등록 모달(프로바이더 드롭다운 — base_url/키 입력 없음)
   을 캡처. provider 1회 등록 → 모델 상속 UX가 화면에서 성립하는지 눈으로 확인.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-providers-035.mjs /tmp/prov035 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/prov035'
const EMAIL = process.env.ADMIN_EMAIL ?? 'verify032@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'Verify032!pw'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
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

  // (1) 프로바이더 탭
  await page.getByText('프로바이더', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-1-providers-list.png`, fullPage: true })
  const provRows = await page.locator('table tbody tr').count()
  // 마스킹 키 노출 여부(• 문자) — 평문/암호문이면 실패 신호.
  const bodyText = await page.locator('table').first().innerText().catch(() => '')
  const hasMask = bodyText.includes('•')
  const leaksCipher = /gAAAAA/.test(bodyText)
  log('STEP1_PROVIDERS rows=' + provRows + ' masked=' + hasMask + ' leaksCipher=' + leaksCipher)

  // (2) 프로바이더 등록 모달
  await page.getByRole('button', { name: '프로바이더 등록' }).click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${OUT}-2-provider-modal.png`, fullPage: true })
  const hasBaseUrl = await page.getByText('Base URL', { exact: true }).count()
  log('STEP2_MODAL baseUrlField=' + hasBaseUrl)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // (3) 모델 탭
  await page.getByText('모델', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-3-models-list.png`, fullPage: true })
  // 헤더에 '프로바이더' 있고 '키' 컬럼 없어야 함.
  const headerText = await page.locator('table thead').first().innerText().catch(() => '')
  log('STEP3_MODELS header=' + JSON.stringify(headerText.replace(/\s+/g, ' ').trim()))

  // (4) 모델 등록 모달 — 프로바이더 드롭다운
  await page.getByRole('button', { name: '모델 등록' }).click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${OUT}-4-model-modal.png`, fullPage: true })
  const hasProviderField = await page.getByText('프로바이더', { exact: true }).count()
  const hasApiKeyField = await page.getByText('API 키', { exact: true }).count()
  log('STEP4_MODEL_MODAL providerField=' + hasProviderField + ' apiKeyField=' + hasApiKeyField)

  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 5)))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
