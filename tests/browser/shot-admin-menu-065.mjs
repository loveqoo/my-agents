/* 어드민 메뉴 그룹 구분 — 스펙 065 검증 (시스템 Chrome, channel:'chrome').
   슈퍼유저 로그인 → 사이드바 캡처: '관리자' 그룹 헤더가 슈퍼유저 항목(유저·배치·허용 호스트)
   위에 뜨고 일반 작업 메뉴와 시각 분리되는지 → collapsed 토글 시 헤더 숨고 아이콘만 남는지
   → 그룹 항목('유저') 클릭 시 뷰 전환 회귀 없는지.

   계정: ADMIN_EMAIL 미지정이면 _fixture.mjs가 던짐용 super를 즉석 시드하고 종료 시 자동 삭제.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-admin-menu-065.mjs /tmp/menu065 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/menu065'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1100, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  log('STEP1_LOGGED_IN')

  // 사이드바(확장)만 캡처 — 232px 폭 클립.
  const sider = page.locator('.ant-layout-sider').first()
  await sider.waitFor({ timeout: 10000 })
  // '관리자' 그룹 헤더가 실제로 렌더되는지 단언(슈퍼유저 게이트 + 그룹 라벨).
  const adminGroup = page.locator('.ant-menu-item-group-title', { hasText: '관리자' })
  await adminGroup.waitFor({ timeout: 10000 })
  const groupTitles = await page
    .locator('.ant-menu-item-group-title')
    .allTextContents()
  log('GROUP_TITLES ' + JSON.stringify(groupTitles.map((t) => t.trim()).filter(Boolean)))
  await page.waitForTimeout(400)
  await sider.screenshot({ path: `${OUT}-1-expanded.png` })
  log('STEP2_SIDEBAR_EXPANDED_CAPTURED')

  // collapsed 토글 — 헤더의 MenuFold 버튼(첫 text 버튼) 클릭 → 72px.
  await page.locator('.ant-layout-header button').first().click()
  await page.waitForTimeout(500)
  // collapsed에서 그룹 라벨은 '' → '관리자' 텍스트가 사라져야 한다(아이콘만).
  const adminVisibleCollapsed = await page
    .locator('.ant-menu-item-group-title', { hasText: '관리자' })
    .count()
  log('ADMIN_LABEL_WHEN_COLLAPSED ' + adminVisibleCollapsed + ' (기대 0 — 라벨 숨김)')
  await sider.screenshot({ path: `${OUT}-2-collapsed.png` })
  log('STEP3_SIDEBAR_COLLAPSED_CAPTURED')

  // 다시 펼치고 그룹 항목('유저') 클릭 → 뷰 전환 회귀 없음.
  await page.locator('.ant-layout-header button').first().click()
  await page.waitForTimeout(400)
  await page.getByText('유저', { exact: true }).first().click()
  // 헤더 타이틀이 '유저'로 바뀌는지(TITLES['users']).
  await page.locator('.ant-layout-header h3', { hasText: '유저' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}-3-users-view.png` })
  log('STEP4_GROUP_ITEM_NAV_OK')

  log(errors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(errors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
  log('MENU065_SHOT_OK')
} catch (e) {
  log('MENU065_SHOT_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png`, fullPage: true }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
  if (_fx) _fx.teardown?.()
}
