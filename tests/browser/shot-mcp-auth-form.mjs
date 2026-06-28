/* 스펙 054 P3-F UI 검증 — 외부 MCP 등록 폼의 인증 스킴 Select + Bearer 토큰
   Input.Password(Fernet 암호화 안내)를 시스템 Chrome으로 캡처한다.

   왜: 라우팅이 React state라 딥링크 불가 → 메뉴 '빌딩 블록' → 탭 'MCP 서버' →
   '외부 MCP 등록' 버튼을 차례로 클릭해 모달을 연다. 인증 스킴을 'Bearer 토큰'으로
   바꿔 토큰 입력 필드와 "Fernet로 암호화 저장" 안내문이 뜨는지 두 컷으로 남긴다.

   실행: PLAYWRIGHT_DIR=<abs> node tests/browser/shot-mcp-auth-form.mjs [out-prefix] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const PREFIX = process.argv[2] ?? '/tmp/mcp-auth'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1200 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  // 로그인 벽이면 env 자격증명(ADMIN_EMAIL/ADMIN_PASSWORD)으로 통과 — 값은 출력하지 않는다.
  const loginBtn = page.getByRole('button', { name: '로그인' })
  if (await loginBtn.count()) {
    await page.locator('input[type="text"], input[type="email"]').first().fill(process.env.ADMIN_EMAIL || '')
    await page.locator('input[type="password"]').first().fill(process.env.ADMIN_PASSWORD || '')
    await loginBtn.first().click()
    await page.waitForTimeout(1800)
  }
  await page.getByText('빌딩 블록', { exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.getByText('MCP 서버', { exact: false }).first().click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: '외부 등록' }).first().click()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${PREFIX}-1-none.png`, fullPage: false })
  console.log('SHOT_OK', `${PREFIX}-1-none.png`)

  // 인증 스킴 Select(기본 '없음')을 열어 'Bearer 토큰' 선택.
  const schemeSel = page.locator('.ant-modal .ant-select').first()
  await schemeSel.click()
  await page.waitForTimeout(400)
  await page.getByText('Bearer 토큰', { exact: true }).first().click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${PREFIX}-2-bearer.png`, fullPage: false })
  console.log('SHOT_OK', `${PREFIX}-2-bearer.png`)

  // 안내문/입력 필드 존재를 DOM으로도 단언(스샷+텍스트 이중 확인).
  const helper = await page.getByText('Fernet', { exact: false }).count()
  const pwField = await page.locator('.ant-modal input[type="password"]').count()
  console.log('ASSERT', JSON.stringify({ fernetHelper: helper, passwordInput: pwField }))
  if (errors.length) console.log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 5)))
} catch (e) {
  console.log('SHOT_FAIL', e.message)
  await page.screenshot({ path: `${PREFIX}-fail.png`, fullPage: false }).catch(() => {})
} finally {
  await browser.close()
}
