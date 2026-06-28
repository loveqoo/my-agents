/* source='code' 에이전트 표시 라벨 'Code/코드' → '원격' 개명 검증 — 시스템 Chrome.
   admin(vite :5173) 로그인 후:
   (1) 에이전트 목록 — code-source 'Doc Translator' 행의 소스 태그가 '원격'으로,
       헤더 액션 버튼이 '원격 에이전트 등록'으로 뜨는지.
   (2) Playground — Doc Translator 선택 시 DebugChat 배지가 '원격 (SDK)'인지.
   내부 enum source='code'는 불변(표시 라벨만 개명). "원격 MCP" 어휘와 일관.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=... ADMIN_PASSWORD=... \
         node tests/browser/shot-remote-label.mjs /tmp/remote-label */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/remote-label'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
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

  // (1) 에이전트 목록.
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-agents-list.png`, fullPage: true })

  const listText = await page.locator('body').innerText().catch(() => '')
  const registerBtn = /원격 에이전트 등록/.test(listText)
  // 소스 태그 '원격'은 짧아 오탐 가능 → 등록 버튼/배지로 함께 교차확인. 목록에 Doc Translator 존재 가정.
  const docTranslator = /Doc Translator/.test(listText)
  const noOldCodeLabel = !/코드 에이전트 등록/.test(listText)
  log('LIST: register_btn(원격 에이전트 등록)=' + registerBtn +
      ' doc_translator=' + docTranslator + ' no_old_label=' + noOldCodeLabel)

  // (2) Playground → Doc Translator 선택 → 배지 '원격 (SDK)'.
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  // 헤더 AgentCombo 버튼(현재 선택 에이전트 이름 포함)을 눌러 드롭다운.
  const combo = page.locator('button').filter({ hasText: 'Research Assistant' }).first()
  await combo.click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${OUT}-2a-combo-open.png`, fullPage: false })
  // 드롭다운(overlay)에서 Doc Translator 선택.
  await page.getByText('Doc Translator', { exact: false }).last().click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-2-playground-badge.png`, fullPage: false })

  const pgText = await page.locator('body').innerText().catch(() => '')
  const remoteBadge = /원격 \(SDK\)/.test(pgText)
  log('PLAYGROUND: remote_badge(원격 (SDK))=' + remoteBadge)

  const ok = registerBtn && noOldCodeLabel && remoteBadge
  log(ok ? 'REMOTE_LABEL_OK' : 'REMOTE_LABEL_SUSPECT')
  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
