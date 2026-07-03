/* 스펙 132(v2) e2e — 사용자 피드백으로 방향 전환: "아이콘만으론 뭔지 모름" → 모바일 헤더는
   세로 스택 3줄(1줄 에이전트 전체폭 이름/모델, 2줄 세션 전체폭 라벨, 3줄 도구 버튼 라벨 포함
   flexWrap)로 온전한 텍스트를 표시한다. 데스크톱은 무변경(한 줄 레이아웃).
   채팅 전송·세션 생성은 하지 않는다(헤더 표면 검증만).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-mobile-header-132.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_MOBILE = process.env.OUT_MOBILE ?? '/tmp/mobile-header-132.png'
const OUT_DESKTOP = process.env.OUT_DESKTOP ?? '/tmp/desktop-header-132.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })

async function login(page) {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
}

// AgentCombo/SessionCombo의 드롭다운 패널은 각 트리거 버튼의 형제(sibling) div로 렌더된다
// (DebugChat.tsx: ref div 안에 button, 그다음 조건부 패널 div) — following-sibling로 안정 포착.
function panelOf(triggerLocator) {
  return triggerLocator.locator('xpath=following-sibling::div[1]')
}

function withinViewport(box, width) {
  if (!box) return false
  return box.x >= -0.5 && box.x + box.width <= width + 0.5
}

// ---------- 모바일 컨텍스트(390x844) ----------
const mobileCtx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 } })
const mp = await mobileCtx.newPage()
try {
  await login(mp)

  // 모바일은 사이더가 기본 접힘(width 0) — 햄버거(헤더의 첫 버튼)로 열고 "Playground" 진입.
  await mp.locator('.ant-layout-header button').first().click()
  await mp.waitForTimeout(300)
  await mp.getByRole('menuitem', { name: 'Playground' }).click()
  await mp.waitForTimeout(300)

  const agentBtn = mp.locator('button:has(.ant-avatar)').first()
  await agentBtn.waitFor({ state: 'visible', timeout: 15000 })
  const sessionBtn = mp.getByTitle(/^세션/)
  await sessionBtn.waitFor({ state: 'visible', timeout: 10000 })
  const headerRow = agentBtn.locator('xpath=../..')

  // M1(v2 — 반전): 에이전트 트리거에 이름 텍스트 표시(아이콘만이 아니라 온전한 텍스트).
  const agentBtnText = (await agentBtn.innerText()).trim()
  check(agentBtnText.length > 0, `M1: 에이전트 트리거에 이름 텍스트 표시(실측: "${agentBtnText.split('\n')[0]}")`)

  // M2(v2 — 반전): 세션 트리거에 라벨("새 세션" 등) 표시.
  const sessionBtnText = (await sessionBtn.innerText()).trim()
  check(sessionBtnText.length > 0, `M2: 세션 트리거에 라벨 표시(실측: "${sessionBtnText}")`)

  // M3: 아바타 탭 → 에이전트 피커 드롭다운 열림 + 화면(390px) 안에 들어옴.
  await agentBtn.click()
  await mp.waitForTimeout(300)
  const agentPanel = panelOf(agentBtn)
  const agentPanelVisible = await agentPanel.isVisible().catch(() => false)
  const agentPanelBox = agentPanelVisible ? await agentPanel.boundingBox() : null
  const m3 = agentPanelVisible && withinViewport(agentPanelBox, 390)
  check(m3, `M3: 에이전트 피커 열림+화면 안(visible=${agentPanelVisible}, box=${JSON.stringify(agentPanelBox)})`)
  await agentBtn.click() // 닫기(토글)
  await mp.waitForTimeout(300)

  // M4: 세션 아이콘 탭 → 세션 드롭다운 열림 + 화면 안.
  await sessionBtn.click()
  await mp.waitForTimeout(300)
  const sessionPanel = panelOf(sessionBtn)
  const sessionPanelVisible = await sessionPanel.isVisible().catch(() => false)
  const sessionPanelBox = sessionPanelVisible ? await sessionPanel.boundingBox() : null
  const m4 = sessionPanelVisible && withinViewport(sessionPanelBox, 390)
  check(m4, `M4: 세션 드롭다운 열림+화면 안(visible=${sessionPanelVisible}, box=${JSON.stringify(sessionPanelBox)})`)
  await sessionBtn.click() // 닫기(토글)
  await mp.waitForTimeout(300)

  // M5(v2 — 반전): 도구 버튼들(오버라이드/시스템 프롬프트/인스펙터)이 라벨 포함 표시
  // (헤더 innerText에 라벨 문자열 존재).
  const headerText = await headerRow.innerText()
  const m5 = /오버라이드/.test(headerText) && /시스템 프롬프트/.test(headerText) && /인스펙터/.test(headerText)
  check(m5, `M5: 도구 버튼 라벨 표시(실측 헤더 텍스트: "${headerText.replace(/\n/g, ' | ')}")`)

  // M6(신규): 헤더 컨테이너에 가로 오버플로 없음 — 세로 스택으로 바뀌며 폭 넘침이 없는지.
  const scrollWidth = await mp.evaluate(() => document.documentElement.scrollWidth)
  check(scrollWidth <= 390, `M6: 가로 오버플로 없음(document.documentElement.scrollWidth=${scrollWidth} <= 390)`)

  await mp.screenshot({ path: OUT_MOBILE, fullPage: false })
  console.log('shot:', OUT_MOBILE)
} catch (e) {
  console.error('ERR(mobile)', e.message)
  await mp.screenshot({ path: OUT_MOBILE, fullPage: false }).catch(() => {})
  fails.push('예외(mobile): ' + e.message)
}

// ---------- 데스크톱 컨텍스트(1400x1100) — 무회귀 ----------
const desktopCtx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const dp = await desktopCtx.newPage()
try {
  await login(dp)
  await dp.getByRole('menuitem', { name: 'Playground' }).click()
  await dp.waitForTimeout(500)

  const agentBtn = dp.locator('button:has(.ant-avatar)').first()
  await agentBtn.waitFor({ state: 'visible', timeout: 15000 })
  const sessionBtn = dp.getByTitle(/^세션/)
  await sessionBtn.waitFor({ state: 'visible', timeout: 10000 })
  const headerRow = agentBtn.locator('xpath=../..')

  // D1: 에이전트 트리거에 이름 텍스트 표시(무회귀).
  const agentBtnText = (await agentBtn.innerText()).trim()
  check(agentBtnText.length > 0, `D1: 에이전트 트리거에 이름 텍스트 표시(실측: "${agentBtnText.split('\n')[0]}")`)

  // D2: 세션 트리거에 라벨("새 세션" 또는 미리보기) 표시 + 한 줄 레이아웃(헤더 높이 < 80px —
  // 모바일 v2의 세로 스택과 달리 무회귀 확인).
  const sessionBtnText = (await sessionBtn.innerText()).trim()
  check(sessionBtnText.length > 0, `D2: 세션 트리거에 라벨 표시(실측: "${sessionBtnText}")`)
  const headerBox = await headerRow.boundingBox()
  const oneLine = !!headerBox && headerBox.height < 80
  check(oneLine, `D2b: 데스크톱 헤더 한 줄 레이아웃(무회귀 — 세로 스택 아님, 실측 헤더 높이 ${headerBox?.height}px < 80)`)

  await dp.screenshot({ path: OUT_DESKTOP, fullPage: false })
  console.log('shot:', OUT_DESKTOP)
} catch (e) {
  console.error('ERR(desktop)', e.message)
  await dp.screenshot({ path: OUT_DESKTOP, fullPage: false }).catch(() => {})
  fails.push('예외(desktop): ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
