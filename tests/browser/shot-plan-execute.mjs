/* 스펙 085 검증 — 커스텀 in-process 에이전트(plan_execute)의 실제 노드 추적을
   플레이그라운드에서 확인한다. 로그인 → Playground → picker에서 'Plan-Execute Demo'
   선택 → 메시지 전송 → 응답의 노드 타임라인([plan, execute])을 인스펙터로 캡처.

   실행:
     PLAYWRIGHT_DIR=/Users/anthony/.npm/_npx/<hash>/node_modules/playwright \
     node tests/browser/shot-plan-execute.mjs /tmp/plan-execute-shot.png */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/plan-execute-shot.png'
const AGENT = process.env.AGENT_NAME ?? 'Plan-Execute Demo'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1300 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
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

  // picker 열기 — 현재 선택 에이전트(기본 'Doc Translator') 이름을 가진 콤보 버튼.
  const combo = page.locator('button', { hasText: 'Doc Translator' }).first()
  await combo.click()
  await page.waitForTimeout(700)

  // 옵션 선택 — 드롭다운 항목 중 에이전트 이름.
  await page.getByText(AGENT, { exact: true }).first().click()
  await page.waitForTimeout(1000)
  log(`PICK: ${AGENT}`)

  // 메시지 전송.
  const input = page.locator('textarea, [contenteditable="true"]').first()
  await input.click().catch(()=>{})
  await input.fill('Compare Redis and Memcached for caching.').catch(async () => { await input.type('Compare Redis and Memcached for caching.') })
  await page.waitForTimeout(300)
  await input.press('Enter').catch(()=>{})
  log('SENT')

  // 응답 스트리밍 완료 감지: 본문 길이가 2회 연속 동일하면 멈춘 것.
  let prev = -1, stable = 0
  for (let i = 0; i < 40; i++) {
    await page.waitForTimeout(1000)
    const len = ((await page.textContent('body').catch(()=>'')) || '').length
    if (len === prev) { stable++; if (stable >= 2) break } else { stable = 0 }
    prev = len
  }
  log('stream settled, body len:', prev)
  await page.waitForTimeout(800)

  // 메시지 하단의 per-turn '인스펙터' 링크 클릭 → 그 턴 트레이스를 패널에 로드.
  // (응답 메타 줄: "N mem · N mcp · Xs · 인스펙터")
  const turnInspector = page.getByText('인스펙터', { exact: true })
  const n = await turnInspector.count()
  log('inspector links:', n)
  await turnInspector.last().click().catch(()=>{})
  await page.waitForTimeout(1500)

  // 인스펙터 패널 영역 텍스트로 노드 확인(헤더 'Plan-Execute' 오탐 배제 위해 패널만).
  const panelText = (await page.locator('text=턴 인스펙터').locator('xpath=ancestor::*[3]').textContent().catch(()=>'')) || ''
  const sawPlan = /\bplan\b/i.test(panelText)
  const sawExec = /\bexecute\b/i.test(panelText)
  log('PANEL plan:', sawPlan, 'execute:', sawExec)

  await page.screenshot({ path: OUT, fullPage: false })
  log('SHOT_OK', OUT)
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 5)))
} catch (e) {
  log('SHOT_FAIL', e.message)
  await page.screenshot({ path: OUT, fullPage: false }).catch(()=>{})
} finally {
  await browser.close()
}
