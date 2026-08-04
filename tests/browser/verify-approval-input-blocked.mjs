/* 스펙 179 P3 — 승인 대기 중 입력 차단(대화 순서 뒤바뀜 방지). 삭제요청→승인대기→입력이 막혀
   새 턴을 못 보냄(placeholder 안내 + textarea disabled). */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import(process.cwd() + '/tests/browser/_fixture.mjs')).provisionSuper()
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
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
  await page.waitForTimeout(1000)

  // 입력 차단 확인: textarea disabled + placeholder 안내
  const disabled = await ta.isDisabled().catch(() => false)
  ok(disabled, '승인 대기 중 입력창 비활성(disabled)')
  const ph = await ta.getAttribute('placeholder').catch(() => '')
  ok(/승인 대기 중/.test(ph || ''), `placeholder 안내 노출 (got: ${ph})`)

  // 강제로 입력·전송 시도해도 새 턴이 안 생겨야(순서 뒤바뀜 방지)
  const before = (await page.locator('#root').innerText()).includes('기다려야')
  await ta.fill('아, 기다려야 하는구나').catch(() => {}) // disabled면 무시됨
  await ta.press('Enter').catch(() => {})
  await page.waitForTimeout(1500)
  const after = (await page.locator('#root').innerText()).includes('기다려야')
  ok(!before && !after, '승인 대기 중 새 메시지 전송 불가(순서 오염 방지)')

  await page.screenshot({ path: '/tmp/input-blocked.png', fullPage: true })
  console.log(fails.length ? `\n실패 ${fails.length}` : '\n스펙 179 P3 입력 차단 — 통과.')
} catch (e) { console.error('오류:', e.message); fails.push(e.message) }
finally { await _fx.cleanup?.(); await browser.close() }
process.exit(fails.length ? 1 : 0)
