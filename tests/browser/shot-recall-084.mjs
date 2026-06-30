/* 메모리 회상 시험 드로어 검증 스크린샷 (스펙 084) — 시스템 Chrome.
   admin(vite :5173) 로그인 후 '메모리' 화면에서:
   (1) 에이전트 메모리 탭 → mem0 에이전트 선택 → '조회 시험' 버튼이 보이는지(084 신규 액션).
   (2) 드로어를 열고 질의 → 결과(회상 카드) 또는 enabled=false 안내가 뜨는지.
   (3) 유저 메모리 탭 → 유저 선택 → '조회 시험' 동일 흐름.
   RecallDrawer는 antd Drawer(.ant-drawer) — 같은 코어(memory.search)로 스코프 질의.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-recall-084.mjs /tmp/recall084 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/recall084'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: Number(process.env.VW ?? 1280), height: 960 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

// 드로어를 열어 질의→조회하고 결과 요약을 로그. 라벨(에이전트/유저)별로 호출.
async function probeDrawer(tag) {
  const openBtn = page.getByRole('button', { name: '조회 시험' }).first()
  if (!(await openBtn.count())) {
    log(`${tag}_OPEN_BTN present=false (선택 항목 없음/패널 미렌더)`)
    return
  }
  await openBtn.click()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}-${tag}-1-open.png`, fullPage: true })

  const ta = page.locator('.ant-drawer textarea').first()
  await ta.fill('내가 선호하는 보고서 형식은?')
  await page.locator('.ant-drawer').getByRole('button', { name: '조회' }).first().click()
  await page.waitForTimeout(2000)
  await page.screenshot({ path: `${OUT}-${tag}-2-result.png`, fullPage: true })

  const dt = await page.locator('.ant-drawer').innerText().catch(() => '')
  const hitCount = (dt.match(/관련도 [\d.]+/g) || []).length
  const hasHeader = /회상 \d+건/.test(dt)
  const disabled = /장기 기억이 비활성\/미구성/.test(dt)
  const empty = /회상된 기억이 없습니다/.test(dt)
  log(`${tag}_RESULT hits=${hitCount} header=${hasHeader} disabledAlert=${disabled} emptyMsg=${empty}`)
  // 드로어 닫기(다음 탭 간섭 방지) — ESC.
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-0-memory.png`, fullPage: true })

  // (1) 에이전트 메모리 탭(기본) — mem0 에이전트 선택.
  const agSel = page.locator('.ant-tabs-tabpane-active .ant-select').first()
  await agSel.click()
  await page.waitForTimeout(500)
  const agOpt = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').first()
  if (await agOpt.count()) {
    await agOpt.click()
    await page.waitForTimeout(900)
    await probeDrawer('agent')
  } else {
    log('agent_NO_OPTION (mem0 ui 에이전트 없음)')
  }

  // (2) 유저 메모리 탭 — 유저 선택.
  await page.getByRole('tab', { name: '유저 메모리' }).click()
  await page.waitForTimeout(900)
  const uSel = page.locator('.ant-tabs-tabpane-active .ant-select').first()
  await uSel.click()
  await page.waitForTimeout(500)
  const uOpt = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').first()
  if (await uOpt.count()) {
    await uOpt.click()
    await page.waitForTimeout(900)
    await probeDrawer('user')
  } else {
    log('user_NO_OPTION (세션 유저 없음)')
  }

  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
