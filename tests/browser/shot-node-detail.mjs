/* 스펙 086 검증 — 턴 인스펙터의 'LangGraph 경로'에 노드별 세부정보(상태 델타 요약 +
   실측 ms)가 화면에 뜨는지 확인한다. 로그인 → Playground → 'Plan-Execute Demo' 선택 →
   메시지 전송 → 인스펙터 열기 → 'LangGraph 경로' 섹션 텍스트 덤프(plan 요약 '핵심' 확인).

   실행:
     PLAYWRIGHT_DIR=/Users/anthony/.npm/_npx/9833c18b2d85bc59/node_modules/playwright \
     node tests/browser/shot-node-detail.mjs /tmp/node-detail-shot.png */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/node-detail-shot.png'
const AGENT = process.env.AGENT_NAME ?? 'Plan-Execute Demo'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1300 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  const loginBtn = page.getByRole('button', { name: /로그인|login|sign in/i }).first()
  if (await loginBtn.isVisible().catch(() => false)) {
    await loginBtn.click(); await page.waitForTimeout(1500); await page.waitForLoadState('networkidle').catch(()=>{})
    log('LOGIN ok')
  }
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)

  const combo = page.locator('button', { hasText: 'Doc Translator' }).first()
  await combo.click(); await page.waitForTimeout(700)
  await page.getByText(AGENT, { exact: true }).first().click()
  await page.waitForTimeout(1000)
  log(`PICK: ${AGENT}`)

  const input = page.locator('textarea, [contenteditable="true"]').first()
  await input.click().catch(()=>{})
  const q = 'Redis와 Memcached를 캐싱 용도로 비교해줘.'
  await input.fill(q).catch(async () => { await input.type(q) })
  await page.waitForTimeout(300)
  await input.press('Enter').catch(()=>{})
  log('SENT')

  // 스트리밍 완료 감지(본문 길이 2회 연속 동일).
  let prev = -1, stable = 0
  for (let i = 0; i < 40; i++) {
    await page.waitForTimeout(1000)
    const len = ((await page.textContent('body').catch(()=>'')) || '').length
    if (len === prev) { stable++; if (stable >= 2) break } else { stable = 0 }
    prev = len
  }
  log('stream settled, body len:', prev)
  await page.waitForTimeout(800)

  // per-turn 인스펙터 링크 클릭.
  const turnInspector = page.getByText('인스펙터', { exact: true })
  await turnInspector.last().click().catch(()=>{})
  await page.waitForTimeout(1500)

  // 'LangGraph 경로' 섹션 영역 텍스트 덤프 — 헤더의 조상에서 섹션 본문 추출.
  const sectionText = (await page
    .locator('text=LangGraph 경로')
    .locator('xpath=ancestor::*[2]')
    .textContent()
    .catch(() => '')) || ''
  const sawPlan = /\bplan\b/i.test(sectionText)
  const sawExec = /\bexecute\b/i.test(sectionText)
  const sawSummary = sectionText.includes('핵심') && sectionText.includes('근거')  // plan 요약
  const sawMsgCount = sectionText.includes('메시지')  // execute 요약
  const msMatches = [...sectionText.matchAll(/\+(\d+)ms/g)].map((m) => Number(m[1]))
  log('PANEL plan:', sawPlan, 'execute:', sawExec)
  log('SUMMARY plan-content:', sawSummary, 'exec-msgcount:', sawMsgCount)
  log('MS values:', JSON.stringify(msMatches))
  log('NODE_DETAIL_086:', JSON.stringify({ sawPlan, sawExec, sawSummary, sawMsgCount, msMatches }))

  await page.screenshot({ path: OUT, fullPage: false })
  log('SHOT_OK', OUT)
} catch (e) {
  log('SHOT_FAIL', e.message)
  await page.screenshot({ path: OUT, fullPage: false }).catch(()=>{})
} finally {
  await browser.close()
}
