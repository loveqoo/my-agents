/* 스펙 135 e2e — 드로어/인스펙터 Escape 닫기 통일. 커스텀 Drawer(shared.tsx — 세션·에이전트)와
   Inspector(전체화면 오버레이)에 Escape 리스너를 추가했고(shared.tsx L293-300, Inspector.tsx L262-269),
   antd Drawer(RAG 컬렉션 문서)는 원래도 Escape로 닫혔다(무회귀 확인 대상).

   판정 방식: 열림 시에만 렌더되는 닫기(X) 아이콘(CloseOutlined → .anticon-close)의 개수로 열림/닫힘을
   판정한다. shared.tsx Drawer는 `{open && (...)}`로 헤더/닫기버튼 자체를 열렸을 때만 마운트하므로
   "제목/닫기버튼 부재"가 곧 닫힘이다(antd Drawer·Inspector도 동일하게 onClose 아이콘이 열림에서만 보임).
   페이지마다 다른 anticon-close 소스가 동시에 뜨지 않아(그때그때 활성 오버레이 하나) 카운트 비교로 충분.

   템플릿=shot-mobile-header-132.mjs(로그인·provisionSuper·모바일 햄버거 내비·채널 chrome headless
   패턴 재사용) + explore로 확인한 셀렉터(세션/RAG/에이전트 행 클릭, Playground 인스펙터 토글 버튼).
   앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-drawer-escape-135.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/escape-135.png'
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

// 모바일: 사이더가 기본 접힘 — 헤더 첫 버튼(햄버거)으로 열고 메뉴 항목을 클릭.
async function mobileNav(page, menuName) {
  await page.locator('.ant-layout-header button').first().click()
  await page.waitForTimeout(400)
  await page.getByRole('menuitem', { name: menuName }).click()
  await page.waitForTimeout(500)
}

const closeIconCount = (page) => page.locator('.anticon-close').count()

// ---------- 모바일 컨텍스트(390x844): E1~E4 ----------
const mobileCtx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 } })
const mp = await mobileCtx.newPage()
try {
  await login(mp)

  // E1: 세션 메뉴 → 행(세션 카드) 클릭 → 커스텀 Drawer 열림 → Escape → 닫힘.
  await mobileNav(mp, '세션')
  await mp.getByText(/^sess-/).first().click()
  await mp.waitForTimeout(500)
  const e1Open = (await closeIconCount(mp)) > 0
  await mp.screenshot({ path: OUT, fullPage: false })
  await mp.keyboard.press('Escape')
  await mp.waitForTimeout(500)
  const e1Closed = (await closeIconCount(mp)) === 0
  check(e1Open && e1Closed, `E1: 세션 커스텀 드로어 Escape 닫힘(열림 판정=${e1Open}, 닫힘 판정=${e1Closed})`)

  // E2: Playground → 헤더 인스펙터 버튼 토글 → 전체화면 오버레이 열림 → Escape → 닫힘(채팅 화면 복귀).
  await mobileNav(mp, 'Playground')
  const inspBtn = mp.getByTitle('인스펙터')
  await inspBtn.click({ timeout: 8000 })
  await mp.waitForTimeout(500)
  const e2Open = (await closeIconCount(mp)) > 0
  await mp.keyboard.press('Escape')
  await mp.waitForTimeout(500)
  const e2Closed = (await closeIconCount(mp)) === 0
  const backToChat = await mp.locator('textarea').first().isVisible().catch(() => false)
  check(e2Open && e2Closed && backToChat, `E2: 인스펙터 오버레이 Escape 닫힘(열림=${e2Open}, 닫힘=${e2Closed}, 채팅 복귀=${backToChat})`)

  // E3(무회귀): RAG 컬렉션 → 행 클릭(antd Drawer, 문서 관리) → Escape → 여전히 닫힘.
  await mobileNav(mp, 'RAG 컬렉션')
  await mp.getByText('docs_kb', { exact: true }).first().click()
  await mp.waitForTimeout(500)
  const e3Open = (await closeIconCount(mp)) > 0
  await mp.keyboard.press('Escape')
  await mp.waitForTimeout(500)
  const e3Closed = (await closeIconCount(mp)) === 0
  check(e3Open && e3Closed, `E3(무회귀): RAG 컬렉션 antd Drawer Escape 닫힘(열림=${e3Open}, 닫힘=${e3Closed})`)

  // E4(무회귀): 에이전트 메뉴 → 카드 클릭(커스텀 Drawer) → Escape → 닫힘.
  await mobileNav(mp, '에이전트')
  await mp.getByText(/^Doc Translator$|^옵시디언 매니저$/).first().click()
  await mp.waitForTimeout(500)
  const e4Open = (await closeIconCount(mp)) > 0
  await mp.keyboard.press('Escape')
  await mp.waitForTimeout(500)
  const e4Closed = (await closeIconCount(mp)) === 0
  check(e4Open && e4Closed, `E4(무회귀): 에이전트 커스텀 드로어 Escape 닫힘(열림=${e4Open}, 닫힘=${e4Closed})`)
} catch (e) {
  console.error('ERR(mobile)', e.message)
  await mp.screenshot({ path: OUT, fullPage: false }).catch(() => {})
  fails.push('예외(mobile): ' + e.message)
}

// ---------- 데스크톱 컨텍스트(1400x1100): E5 ----------
const desktopCtx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const dp = await desktopCtx.newPage()
try {
  await login(dp)
  await dp.getByRole('menuitem', { name: '세션' }).click()
  await dp.waitForTimeout(500)
  await dp.getByText(/^sess-/).first().click()
  await dp.waitForTimeout(500)
  const e5Open = (await closeIconCount(dp)) > 0
  await dp.keyboard.press('Escape')
  await dp.waitForTimeout(500)
  const e5Closed = (await closeIconCount(dp)) === 0
  check(e5Open && e5Closed, `E5: 데스크톱 세션 드로어 Escape 닫힘(열림=${e5Open}, 닫힘=${e5Closed})`)
} catch (e) {
  console.error('ERR(desktop)', e.message)
  fails.push('예외(desktop): ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log('shot:', OUT)
console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
