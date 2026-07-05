/* 스펙 182 P3 — ApprovalsView 중복 추출(CardHeaderRow·PermActionTags) 후 시각 회귀 확인.
   던짐용 super로 delete_record 승인 1건 생성 → 대기중 탭(ApprovalCard) 캡처 → 승인 → 처리됨 탭(HistoryCard) 캡처. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import(process.cwd() + '/tests/browser/_fixture.mjs')).provisionSuper()
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const combo = page.locator('button').filter({ hasText: 'research-assistant' }).first()
  if (await combo.count()) { await combo.click(); await page.waitForTimeout(300)
    await page.getByText('research-assistant', { exact: false }).first().click().catch(()=>{}); await page.waitForTimeout(500) }
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('레코드 r1 삭제해줘'); await ta.press('Enter')
  await page.getByText(/승인 대기/i).first().waitFor({ timeout: 25000 })

  // 승인 화면 대기중 탭(ApprovalCard)
  await page.getByText('승인', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: '/tmp/182-approval-pending.png', fullPage: true })
  // 승인 처리 → 처리됨 탭(HistoryCard)
  await page.getByRole('button', { name: /승인 및 재개/ }).first().click()
  await page.waitForTimeout(3500)
  await page.getByText('처리됨', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: '/tmp/182-approval-history.png', fullPage: true })
  console.log('캡처 완료: /tmp/182-approval-pending.png, /tmp/182-approval-history.png')
} catch (e) { console.error('오류:', e.message); await page.screenshot({path:'/tmp/182-err.png'}).catch(()=>{}) }
finally { await _fx.cleanup?.(); await browser.close() }
