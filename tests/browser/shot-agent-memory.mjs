/* 스펙 029 검증 — Admin 에이전트 상세의 "에이전트 지식 (mem0)" 패널 캡처.
   ui-소스 + 장기기억 에이전트(Research Assistant)를 열어 AgentMemoryPanel이
   렌더되는지, add/list가 동작하는지 화면으로 확인한다.

   실행: PLAYWRIGHT_DIR=<npx>/node_modules/playwright node tests/browser/shot-agent-memory.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/agent-memory-shot.png'
const AGENT = process.env.AGENT_NAME ?? 'Research Assistant'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1400 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  // 사이드 메뉴 '에이전트' 클릭.
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(800)
  // 에이전트 행 클릭(이름으로).
  await page.getByText(AGENT, { exact: true }).first().click()
  await page.waitForTimeout(1200)
  // 패널 라벨이 보일 때까지 스크롤.
  const panel = page.getByText('에이전트 지식 (mem0)', { exact: false }).first()
  const found = await panel.count()
  if (found) {
    await panel.scrollIntoViewIfNeeded().catch(() => {})
    await page.waitForTimeout(1500) // listAgentMemory fetch 반영 대기
    console.log('PANEL_FOUND')
  } else {
    console.log('PANEL_NOT_FOUND')
  }
  await page.screenshot({ path: OUT, fullPage: true })
  console.log('SHOT_OK', OUT)
  if (errors.length) console.log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 6)))
} catch (e) {
  console.log('SHOT_FAIL', e.message)
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
} finally {
  await browser.close()
}
