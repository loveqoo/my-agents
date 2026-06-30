/* picker 드롭다운 열고 에이전트 목록 캡처(디버그용). */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(`${pwDir}/index.js`)
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/picker-shot.png'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1300 } })
const page = await ctx.newPage()
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  const loginBtn = page.getByRole('button', { name: /로그인|login|sign in/i }).first()
  if (await loginBtn.isVisible().catch(() => false)) { await loginBtn.click(); await page.waitForTimeout(1500); await page.waitForLoadState('networkidle').catch(()=>{}) }
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  // 에이전트 콤보: 현재 'Doc Translator' 텍스트를 가진 버튼.
  const combo = page.locator('button', { hasText: 'Doc Translator' }).first()
  await combo.click()
  await page.waitForTimeout(800)
  // dropdown 옵션 텍스트 수집.
  const texts = await page.locator('[class*="dropdown"], [role="listbox"], [class*="menu"]').allTextContents().catch(()=>[])
  console.log('DROPDOWN_TEXT:', JSON.stringify(texts).slice(0, 600))
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT_OK', OUT)
} catch (e) { console.log('FAIL', e.message); await page.screenshot({ path: OUT }).catch(()=>{}) }
finally { await browser.close() }
