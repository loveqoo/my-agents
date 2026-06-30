/* 스펙 083 검증 — A2A 노출 토글이 로컬(ui) 에이전트에만 보이는지(시스템 Chrome).
   admin(vite :5173) 로그인 후 에이전트 목록에서:
   (1) 표 '공개' 열 — 원격(code) 행 'Doc Translator' 인근에 '—'(노출 불가 표식),
       ui 행은 토글/'A2A'·'꺼짐'. 목록 캡처.
   (2) ui 에이전트(Research Assistant) 드로어 → 'A2A로 공개' 토글 *있음*.
   (3) code 에이전트(Doc Translator) 드로어 → 'A2A로 공개' 토글 *없음*(스펙 083 핵심).

   라벨 'A2A로 공개'는 ui 드로어(AgentDetail)에만 렌더 — code/external 디테일에선 제거됨.
   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-expose-gate-083.mjs /tmp/expose-083 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/expose-083'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

// shared Drawer는 antd가 아니라 커스텀 div(클래스 없음). 한 번에 하나만 열리므로
// 행 클릭 → 애니메이션 대기 → 페이지 전체에서 'A2A로 공개' 보이는 노드 수로 판정.
async function openRowDrawer(rowName, shot) {
  await page.getByText(rowName, { exact: false }).first().click()
  await page.waitForTimeout(1300) // 드로어 translateX 애니메이션(250ms) + 렌더 여유
  await page.screenshot({ path: shot, fullPage: false })
  return (await page.getByText('A2A로 공개', { exact: false }).count()) > 0
}

async function closeDrawer() {
  // mask는 콘텐츠 영역(사이드바 x≈230 우측)만 덮음. 패널(우측 480px) 왼쪽·사이드바 오른쪽인
  // x=500을 클릭해야 mask onClose가 발화(사이드바 위 클릭은 mask 밖이라 무효).
  await page.mouse.click(500, 500)
  await page.waitForTimeout(700)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // (1) 에이전트 목록 — 공개 열.
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-list.png`, fullPage: true })

  // 표에서 Doc Translator(code) 행을 찾아 같은 행에 '—'(em dash) 표식이 있는지.
  const docRow = page.locator('tr', { hasText: 'Doc Translator' }).first()
  const docRowText = await docRow.innerText().catch(() => '')
  const docHasDash = docRowText.includes('—')
  log('LIST: doc(code) row has em-dash(노출불가)=' + docHasDash + '  rowtext=' + JSON.stringify(docRowText.slice(0, 120)))

  // (2) ui 드로어 — Research Assistant: 토글 *있음*.
  const uiHasToggle = await openRowDrawer('Research Assistant', `${OUT}-2-ui-drawer.png`)
  log('UI DRAWER(Research Assistant): has A2A toggle=' + uiHasToggle)
  await closeDrawer()

  // (3) code 드로어 — Doc Translator: 토글 *없음*.
  const codeHasToggle = await openRowDrawer('Doc Translator', `${OUT}-3-code-drawer.png`)
  const codeNoToggle = !codeHasToggle
  log('CODE DRAWER(Doc Translator): NO A2A toggle=' + codeNoToggle)
  await closeDrawer()

  const ok = docHasDash && uiHasToggle && codeNoToggle
  log(ok ? 'EXPOSE_GATE_083_OK' : 'EXPOSE_GATE_083_SUSPECT')
  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
  if (!ok) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
