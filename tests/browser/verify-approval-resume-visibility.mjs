/* 스펙 179 fix 검증 — 승인 후 요청자 채팅 자동 갱신(폴링). 사용자 2브라우저 시나리오:
   1) 브라우저1: 삭제요청→승인 대기  2) 브라우저2: 승인  3) 브라우저1: 폴링으로 완료 턴 자동 표시. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import(process.cwd() + '/tests/browser/_fixture.mjs')).provisionSuper()
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const login = async (p) => {
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await p.getByPlaceholder('you@example.com').fill(_fx.email)
  await p.getByPlaceholder('비밀번호').fill(_fx.password)
  await p.getByRole('button', { name: '로그인' }).click()
  await p.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
}
try {
  // 브라우저1(요청자)
  const ctx1 = await browser.newContext({ viewport: { width: 1400, height: 950 } })
  const page = await ctx1.newPage()
  await login(page)
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const combo = page.locator('button').filter({ hasText: 'research-assistant' }).first()
  if (await combo.count()) { await combo.click(); await page.waitForTimeout(300)
    await page.getByText('research-assistant', { exact: false }).first().click().catch(()=>{}); await page.waitForTimeout(500) }
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('레코드 r1 삭제해줘'); await ta.press('Enter')
  await page.getByText(/승인 대기/i).first().waitFor({ timeout: 25000 })
  ok(true, '브라우저1: 승인 대기 표시')

  // 브라우저2(승인자) — 별개 컨텍스트
  const ctx2 = await browser.newContext({ viewport: { width: 1200, height: 900 } })
  const page2 = await ctx2.newPage()
  await login(page2)
  await page2.getByText('승인', { exact: true }).first().click()
  await page2.waitForTimeout(1000)
  await page2.getByRole('button', { name: /승인 및 재개|승인|approve/i }).first().click()
  await page2.waitForTimeout(2500)
  ok(true, '브라우저2: 승인 및 재개 클릭')

  // 브라우저1: 폴링(2.5s)로 자동 갱신되는지 — 최대 ~20s 관찰. 승인 대기가 완료 턴으로 바뀌어야.
  let updated = false
  for (let i = 0; i < 10; i++) {
    await page.waitForTimeout(2600)
    const body = await page.locator('#root').innerText()
    // 완료 턴 = mock 재개 응답 본문('결정적 mock 응답')이 뜨고, '승인 대기'·빈세션 상태는 사라짐.
    // ('mock-llm'은 헤더 배지라 오탐 → 응답 본문 문구로 판정)
    const hasReply = /결정적 mock 응답/.test(body)
    const stillStuck = /승인 대기/.test(body)
    const emptyState = /불러올 메시지가 없/.test(body)
    if (hasReply && !stillStuck && !emptyState) { updated = true; break }
  }
  await page.screenshot({ path: '/tmp/resume-autoupdate.png', fullPage: true })
  ok(updated, '브라우저1: 승인 후 폴링으로 완료 턴 자동 표시(더 이상 멈춰있지 않음)')

  await ctx2.close(); await ctx1.close()
  console.log(fails.length ? `\n실패 ${fails.length}` : '\n스펙 179 승인 자동 갱신 — 통과.')
} catch (e) { console.error('오류:', e.message); fails.push(e.message) }
finally { await _fx.cleanup?.(); await browser.close() }
process.exit(fails.length ? 1 : 0)
