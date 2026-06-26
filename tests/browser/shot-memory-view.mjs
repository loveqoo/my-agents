/* 스펙 030 검증 — Admin '메모리' 메뉴(통합 화면) 캡처.
   에이전트 탭(AgentMemoryPanel 재사용)·유저 탭(UserMemoryPanel)을 차례로 열어
   목록·필터가 렌더되는지 화면으로 확인한다. 유저 탭에서는 alice를 골라
   라이브로 적재된 user_id 기억이 나오는지, 필터가 거르는지 본다.

   실행: PLAYWRIGHT_DIR=<npx>/node_modules/playwright node tests/browser/shot-memory-view.mjs [outPrefix] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const PREFIX = process.argv[2] ?? '/tmp/memory-view'
const USER = process.env.USER_ID ?? 'alice'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1200 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

async function pick(optionText) {
  // antd Select(showSearch): 보이는 셀렉트를 클릭해 열고, 검색어를 타이핑해
  // 옵션을 거른 뒤 드롭다운 항목을 클릭한다. 포털(.ant-select-dropdown)에 렌더된다.
  const sel = page.locator('.ant-select:visible').first()
  await sel.click()
  await page.waitForTimeout(300)
  const search = page.locator('.ant-select-dropdown:visible input, .ant-select:visible input').last()
  await search.fill(optionText).catch(() => {})
  await page.waitForTimeout(500)
  const opt = page.locator('.ant-select-item-option:visible', { hasText: optionText }).first()
  await opt.click({ timeout: 5000 }).catch(async () => {
    await page.getByTitle(optionText, { exact: true }).first().click({ timeout: 5000 }).catch(() => {})
  })
  await page.waitForTimeout(1500)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  // 사이드 메뉴 '메모리' 클릭.
  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(800)
  console.log('MEMORY_MENU', await page.getByText('에이전트 메모리', { exact: true }).count() ? 'OPEN' : 'MISS')

  // --- 에이전트 탭 ---
  await page.getByRole('tab', { name: '에이전트 메모리' }).click().catch(() => {})
  await page.waitForTimeout(400)
  await pick('Research Assistant')
  await page.screenshot({ path: `${PREFIX}-agent.png`, fullPage: true })
  console.log('SHOT_AGENT', `${PREFIX}-agent.png`)

  // --- 유저 탭 ---
  await page.getByRole('tab', { name: '유저 메모리' }).click()
  await page.waitForTimeout(500)
  await pick(USER)
  await page.waitForTimeout(1200)
  const userMem = await page.getByText('favorite color', { exact: false }).count()
  console.log('USER_MEM_ROWS', userMem)
  await page.screenshot({ path: `${PREFIX}-user.png`, fullPage: true })
  console.log('SHOT_USER', `${PREFIX}-user.png`)

  // --- 필터 동작: 'teal' 입력 시 색상 행만, 매칭 0이면 빈상태 ---
  // antd Tabs는 비활성 탭도 마운트(display:none)하므로 보이는 인풋만 잡는다.
  const filter = page.getByPlaceholder('필터 (텍스트 부분일치)').locator('visible=true')
  if (await filter.count()) {
    await filter.first().fill('zzzznomatch')
    await page.waitForTimeout(500)
    console.log('FILTER_EMPTY', await page.getByText('필터에 맞는 기억이 없습니다').count() ? 'OK' : 'MISS')
    await filter.first().fill('color')
    await page.waitForTimeout(500)
    await page.screenshot({ path: `${PREFIX}-user-filter.png`, fullPage: true })
    console.log('SHOT_FILTER', `${PREFIX}-user-filter.png`)
  } else {
    console.log('FILTER_INPUT_MISS')
  }

  if (errors.length) console.log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 6)))
} catch (e) {
  console.log('SHOT_FAIL', e.message)
  await page.screenshot({ path: `${PREFIX}-fail.png`, fullPage: true }).catch(() => {})
} finally {
  await browser.close()
}
