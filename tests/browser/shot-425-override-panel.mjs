/* 오버라이드 패널 실물 정찰(스펙 425 검증 준비) — 셀렉터 확정용 스샷만. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
try {
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.waitForTimeout(1500)
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  const combo = page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first()
  if (await combo.count()) { await combo.click(); await page.getByText('personal-secretary').first().click(); await page.waitForTimeout(800) }
  await page.getByText('오버라이드', { exact: false }).first().click()
  await page.waitForTimeout(1000)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(800); await page.screenshot({ path: 'tests/browser/out-tmp/v425-override-step2.png', fullPage: false })
  console.log('SHOT')
} catch (e) { console.log('EXC', e.message) } finally { await browser.close() }
