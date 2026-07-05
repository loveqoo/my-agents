/* 스펙 178 P3 — 평가 메뉴 일반 접근 이동 + "결과 공개" 안내 렌더. 시스템 Chrome. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/eval-178'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)
  await page.getByText('평가', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const alert = await page.getByText('평가 결과는 모든 사용자에게 공개', { exact: false }).count()
  ok(alert > 0, `'평가 결과 공개(모든 사용자)' 안내 렌더 (found=${alert})`)
  await page.screenshot({ path: `${OUT}.png`, fullPage: true })
  console.log(fails.length ? `\n실패 ${fails.length}` : '\nP3 평가 개방 UI — 통과.')
} catch (e) { console.error('오류:', e.message); fails.push(e.message) }
finally { if (_fx) await _fx.cleanup?.(); await browser.close() }
process.exit(fails.length ? 1 : 0)
