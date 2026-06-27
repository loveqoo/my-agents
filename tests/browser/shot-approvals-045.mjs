/* 스펙 045 검증 스크린샷 — 승인 사이드바 배지 == 실제 pending 목록 카드 수(#12).
   #12 버그: 배지가 mock 상수(2)였고 목록은 백엔드 전량(8)이라 불일치였다. 045는 배지를
   실제 pending 수로, 목록을 pending-only로 정직화. 여기서 둘이 *같은 수*인지 눈+숫자로 확인.

   실행: PLAYWRIGHT_DIR=<절대경로>/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-approvals-045.mjs /tmp/approvals-045.png */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/approvals-045.png'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  // 로그인
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  // 마운트 시 AdminShell이 listApprovals('pending')로 배지를 채울 시간.
  await page.waitForTimeout(1200)

  // 사이드바 배지 수 읽기(승인 메뉴의 .ant-badge-count). 0이면 배지 미렌더(숨김)→0으로 간주.
  const sider = page.locator('.ant-layout-sider')
  const badgeEl = sider.locator('.ant-badge-count').first()
  const badgeText = (await badgeEl.count()) ? (await badgeEl.innerText()).trim() : '0'
  const badge = parseInt(badgeText.replace(/[^0-9]/g, '') || '0', 10)
  log('SIDEBAR_BADGE=' + badge)

  // 승인 뷰 진입 — 라벨에 배지가 붙어 텍스트 exact 매칭이 깨지므로 menuitem(name 정규식)로.
  await page.getByRole('menuitem', { name: /승인/ }).first().click()
  await page.waitForTimeout(1200)
  // 목록 카드 수 = "승인 및 재개" 버튼 수(카드당 1개). 빈 상태면 0.
  const cards = await page.getByRole('button', { name: '승인 및 재개' }).count()
  const emptyState = await page.getByText('대기 중인 승인이 없습니다', { exact: false }).count()
  log('LIST_CARDS=' + cards + ' EMPTY_STATE=' + emptyState)

  await page.screenshot({ path: OUT, fullPage: false })
  log('SHOT_OK', OUT)

  // 판정: 배지 == 목록 카드 수(둘 다 0이면 빈 상태와도 정합).
  if (badge === cards) log('MATCH_OK badge==cards (' + badge + ')')
  else log('MATCH_FAIL badge=' + badge + ' cards=' + cards)

  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
  else log('NO_CONSOLE_ERRORS')
} catch (e) {
  log('APPROVALS_045_FAIL', e.message)
  await page.screenshot({ path: OUT.replace('.png', '-FAIL.png') }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
