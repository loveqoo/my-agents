const _pw = await import(`${process.env.PLAYWRIGHT_DIR}/index.js`)
const chromium = _pw.chromium ?? _pw.default?.chromium
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
const log = (...a) => console.log(...a)
try {
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill('admin@example.com')
  await page.getByPlaceholder('비밀번호').fill('adminpass123')
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  // 에이전트 선택 드롭다운 → approval-demo
  await page.locator('button').filter({ hasText: 'research-assistant' }).first().click()
  await page.waitForTimeout(600)
  await page.screenshot({ path: '/tmp/appr-dropdown.png' })
  const opt = page.getByText('approval-demo', { exact: false }).first()
  await opt.waitFor({ timeout: 5000 })
  await opt.click()
  await page.waitForTimeout(800)
  const ph = await page.locator('textarea').first().getAttribute('placeholder')
  log('선택 후 placeholder:', ph)

  // 메시지 전송
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('내 생일은 3월 3일이야. 기억해줘.')
  await ta.press('Enter')
  log('전송함 — 승인 대기 관찰...')
  // 승인 신호 대기 (승인/approval/대기/pending 텍스트)
  const appeared = await page.getByText(/승인 대기|승인이 필요|approval|승인해|memory\.write|기억에 저장/i).first()
    .waitFor({ timeout: 20000 }).then(()=>true).catch(()=>false)
  await page.waitForTimeout(1500)
  await page.screenshot({ path: '/tmp/appr-fired.png', fullPage: true })
  log('승인 신호 나타남:', appeared)
  const body = await page.locator('#root').innerText()
  log('본문에 "승인" 포함:', body.includes('승인'))
  log('본문 발췌:', body.split('\n').filter(s=>/승인|기억|memory|대기|pending/i.test(s)).slice(0,8).join(' | '))
} catch (e) { log('ERR', e.message); await page.screenshot({path:'/tmp/appr-fired.png'}).catch(()=>{}) }
finally { await browser.close() }
