/* 스펙 181 — 승인 내역(감사) 화면. member가 승인/거부 후 승인 화면의 '처리됨' 탭에서
   결과(승인됨/거부됨)·처리 시각·본인 처리를 확인. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const EMAIL = process.env.MEMBER_EMAIL ?? 'shotfix_selfdemo@example.com'
const PASSWORD = process.env.MEMBER_PASSWORD ?? 'Selfdemo1!pw'
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
const triggerAndResolve = async (rec, decision) => {
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(900)
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill(`레코드 ${rec} 삭제해줘`); await ta.press('Enter')
  await page.getByText(/승인 대기/i).first().waitFor({ timeout: 25000 })
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: decision === 'approve' ? /승인 및 재개/ : '거부' }).first().click()
  await page.waitForTimeout(decision === 'approve' ? 4000 : 1500)
}
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  // 데모 에이전트 선택
  await page.getByText('Playground', { exact: true }).first().click(); await page.waitForTimeout(1000)
  const combo = page.locator('button').filter({ hasText: /self-approval-demo|본인 승인 데모|research-assistant/ }).first()
  await combo.click(); await page.waitForTimeout(400)
  await page.getByText(/self-approval-demo|본인 승인 데모/, { exact: false }).first().click().catch(()=>{})
  await page.waitForTimeout(500)

  // 승인 1건 + 거부 1건 만들기(인라인)
  await triggerAndResolve('h1', 'approve')
  await triggerAndResolve('h2', 'reject')

  // 승인 화면 → 처리됨 탭
  await page.getByText('승인', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.getByText('처리됨', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  const body = await page.locator('#root').innerText()
  ok(/승인됨/.test(body), '처리됨 탭에 "승인됨" 결과 노출')
  ok(/거부됨/.test(body), '처리됨 탭에 "거부됨" 결과 노출')
  ok(/본인 처리/.test(body), '"본인 처리" 표기(resolvedBySelf)')
  ok(/처리 시각 20\d\d-/.test(body), '처리 시각 실제 값 노출(ISO)') // 레거시 NULL 행은 "—"(정상), 신규는 시각
  await page.screenshot({ path: '/tmp/approval-history.png', fullPage: true })
  console.log(fails.length ? `\n실패 ${fails.length}` : '\n스펙 181 승인 내역 — 통과.')
} catch (e) { console.error('오류:', e.message); fails.push(e.message); await page.screenshot({path:'/tmp/approval-history-err.png'}).catch(()=>{}) }
finally { await browser.close() }
process.exit(fails.length ? 1 : 0)
