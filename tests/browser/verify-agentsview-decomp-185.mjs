/* 스펙 185 Phase A — AgentsView 서브컴포넌트 파일 분리 후 회귀.
   순환 import·잘못된 import 경로면 드로어/폼이 빈 채로 깨진다 → 전부 열어 렌더 확인. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-{{GITHUB_ORG}}-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1360, height: 960 } })
const page = await ctx.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
const log = (...a) => console.log(...a)
let fail = 0
const check = (ok, name) => { log(`${ok ? ' ok ' : 'FAIL'} ${name}`); if (!ok) fail++ }
const closeDrawer = async () => { await page.keyboard.press('Escape'); await page.waitForTimeout(500) }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1500)

  // 1) 리스트 렌더
  const rowCount = await page.locator('table tbody tr').count()
  check(rowCount > 0, `L1 에이전트 리스트 렌더 (${rowCount}행)`)

  // 2) 상세 드로어 — source별로 열어 3 컴포넌트(AgentDetail/CodeAgentDetail/ExternalAgentDetail) 실증
  //    seed 이름: plan-execute-demo(ui), doc-translator(code), acme-translate(external)
  // shared.Drawer는 커스텀(className·role 없음, 닫힘=translateX off-screen). 각 드로어에만 나오는
  // 고유 라벨을 Playwright 가시성으로 판정 — off-screen 닫힌 드로어는 Playwright가 hidden 처리.
  const openByName = async (namePart, label, uniqueText) => {
    const cell = page.locator('table tbody tr', { hasText: namePart }).first()
    if (await cell.count() === 0) { log(` -- ${label}: '${namePart}' 행 없음(seed 차이) — 스킵`); return }
    await cell.click()
    const marker = page.getByText(uniqueText, { exact: false }).first()
    let visible = false
    try { await marker.waitFor({ state: 'visible', timeout: 3000 }); visible = true } catch { /* below */ }
    check(visible, `${label} 드로어 렌더 (고유 '${uniqueText}' 노출)`)
    await page.screenshot({ path: `${OUT}/decomp-185-${label}.png` })
    await closeDrawer()
  }
  await openByName('plan-execute', 'D-ui', '공개 범위')
  await openByName('translator', 'D-code', '배포 히스토리')
  await openByName('acme', 'D-external', '제공자')

  // 3) 생성 폼(AgentForm) — 종류 전환·필드 렌더
  await page.getByRole('button', { name: '새 에이전트' }).click()
  await page.waitForTimeout(800)
  const fm = page.locator('.ant-modal-body:visible').last()
  const formText = (await fm.count()) ? (await fm.textContent()) ?? '' : ''
  check(/에이전트 생성|종류/.test(formText) && /이름|프롬프트|모델/.test(formText),
    `F1 생성 폼(AgentForm) 렌더 (${formText.length}자)`)
  await page.screenshot({ path: `${OUT}/decomp-185-form.png` })
  await page.keyboard.press('Escape'); await page.waitForTimeout(500)

  // 4) 연결 모달(ConnectAgentModal)
  await page.getByRole('button', { name: '원격 에이전트 연결' }).click()
  await page.waitForTimeout(700)
  const cm = page.locator('.ant-modal-body:visible').last()
  const connText = (await cm.count()) ? (await cm.textContent()) ?? '' : ''
  check(/원격|연결|URL|카드/.test(connText) && connText.length > 20,
    `C1 연결 모달(ConnectAgentModal) 렌더 (${connText.length}자)`)
  await page.keyboard.press('Escape'); await page.waitForTimeout(400)

  // 5) 런타임 에러 0 (순환 import·모듈 로드 실패면 pageerror)
  check(pageErrors.length === 0, `Z1 pageerror 0 (실제: ${pageErrors.length})`)
  if (pageErrors.length) log('  pageerrors:', pageErrors.slice(0, 3))
  const realConsole = consoleErrors.filter((e) => !/favicon|404|401|is deprecated/.test(e))
  check(realConsole.length === 0, `Z2 콘솔 에러 0 (실제: ${realConsole.length})`)
  if (realConsole.length) log('  console:', realConsole.slice(0, 4))

  log(fail === 0 ? '\n✅ ALL PASS (DECOMP185_OK)' : `\n❌ ${fail} FAILED`)
} catch (e) {
  log('EXCEPTION:', String(e))
  fail++
} finally {
  await browser.close()
}
process.exit(fail === 0 ? 0 : 1)
