/* 원격 에이전트 연결 모달 문구 다이어트 스냅샷 + 단언.
   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright node tests/browser/shot-connect-modal-trim.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByRole('menuitem', { name: '에이전트' }).click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /원격 에이전트 연결/ }).click()
  await page.waitForTimeout(600)
  const modal = page.getByRole('dialog')

  check((await modal.locator('.ant-alert').count()) === 0, 'Alert 배너 부재')
  check((await modal.getByText('URL 하나만 입력하세요', { exact: false }).count()) === 0, '구 안내문 부재')
  check((await modal.getByText('SSRF', { exact: false }).count()) === 0, 'SSRF 용어 부재')
  check((await modal.getByText('자동 분류합니다', { exact: false }).count()) === 1, 'URL 힌트 1건')
  check((await modal.getByText('A2A_ALLOWED_HOSTS', { exact: false }).count()) === 1, '허용 호스트 안내 1건')
  await modal.screenshot({ path: 'tests/browser/out-connect-modal-trim.png' })

  console.log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  console.log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
