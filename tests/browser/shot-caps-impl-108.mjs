/* 스펙 108 검증 — 폼 재구성: 유저 언어 + 종류가 설정을 가른다. 시스템 Chrome.
   직접 응답=직접 자원 칸, 조율형="무엇에 맡길까요?"만. 내부어(impl·브로커·위임·오케스트레이터)·
   기술 id(memory:user·mcp:·rag:·agt_) 화면에 없음.

   실행: ADMIN_URL=http://localhost:5173 PLAYWRIGHT_DIR=<abs> node tests/browser/shot-caps-impl-108.mjs /tmp/caps-108 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://localhost:5173'
const OUT = process.argv[2] ?? '/tmp/caps-108'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1200 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let fails = 0
const check = (cond, msg) => { log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails++ }
const modalText = async () => (await page.locator('.ant-modal-container').innerText())

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(800)
  const modal = page.locator('.ant-modal-container')

  // ── 상태 1: 직접 응답(기본) ──
  const t1 = await modalText()
  check(t1.includes('에이전트 종류'), 'H1 "에이전트 종류" 필드 존재(impl 단어 대체)')
  check(t1.includes('메모리 타입') && t1.includes('권한') && t1.includes('도구 (MCP)'),
    'H1 직접 응답 → 직접 자원 칸(메모리·권한·도구) 보임')
  check(!t1.includes('무엇에 맡길까요'), 'H1 직접 응답 → "무엇에 맡길까요" 칸 없음')
  await page.getByText('에이전트 종류', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${OUT}-direct.png`, fullPage: true })

  // ── 종류를 조율형으로 ──
  const typeSelect = page.getByText('에이전트 종류', { exact: true })
    .locator('xpath=following-sibling::*[contains(@class,"ant-select")][1]')
  await typeSelect.click()
  await page.waitForTimeout(300)
  await page.getByText('조율형', { exact: true }).click()
  await page.waitForTimeout(400)

  // ── 상태 2: 조율형 ──
  const t2 = await modalText()
  check(t2.includes('무엇에 맡길까요'), 'H2 조율형 → "무엇에 맡길까요?" 칸 등장')
  check(!t2.includes('메모리 타입') && !t2.includes('도구 (MCP)') && !t2.includes('지식 소스'),
    'H2 조율형 → 직접 자원 칸 사라짐(중복 제거)')
  check(t2.includes('다른 에이전트') && t2.includes('문서') && t2.includes('사용자 기억'),
    'H2 위임 kind 유저어(다른 에이전트·문서·사용자 기억)')

  // ── 내부어·기술 id 부재(두 상태 합쳐) ──
  const both = t1 + '\n' + t2
  const jargon = ['impl', '브로커', '위임', '오케스트레이'].filter((w) => both.includes(w))
  check(jargon.length === 0, `H3 내부어 없음(발견: ${JSON.stringify(jargon)})`)
  const ids = ['memory:user', 'memwrite:user', 'mcp:', 'rag:', 'agt_'].filter((w) => both.includes(w))
  check(ids.length === 0, `H4 기술 id 없음(발견: ${JSON.stringify(ids)})`)

  // ── 조율형 저장 왕복(맡길 대상 체크 → 저장 → 재열기 반영) ──
  await modal.locator('.ant-collapse-header').filter({ hasText: '사용자 기억' }).click()
  await page.waitForTimeout(300)
  await modal.locator('label.ant-checkbox-wrapper', { hasText: '사용자 기억 읽기' }).locator('input').check()
  await page.waitForTimeout(200)
  check(await modal.locator('.ant-collapse-header').filter({ hasText: '사용자 기억' }).getByText('1/2').count() > 0,
    'H5 위임 대상 체크 → 카운트 1/2 반영')

  await page.getByText('무엇에 맡길까요?', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${OUT}-orchestrator.png`, fullPage: true })

  log('SHOT ' + OUT + '-direct.png / ' + OUT + '-orchestrator.png')
  log(fails === 0 ? 'VERIFY108_OK' : `VERIFY108_FAIL(${fails})`)
  if (fails) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
