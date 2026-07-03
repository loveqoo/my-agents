/* 스펙 155 e2e — 플레이그라운드 A2A 루프백 테스트 브라우저 검증.
   (K1) 플레이그라운드 진입 → 에이전트 피커에서 "Research Assistant"(research-assistant, ui,
        exposed.a2a=True) 선택 → 헤더에 "직접"/"A2A" Segmented 토글이 보인다.
   (K2) 토글에서 "A2A" 클릭 → 선택 상태로 전환된다.
   (K3) 메시지 입력 후 전송 → A2A 경유 응답이 ai 버블에 비어있지 않은 텍스트로 렌더된다
        (최대 60초 대기).
   (K4) 피커에서 "Personal Secretary"(personal-secretary, ui, exposed.a2a=False, 미노출) 선택
        → 헤더에 A2A 토글(Segmented)이 없다.

   앱 코드 수정 없음 — 검증 전용. 앱 상태(에이전트 노출 여부)도 바꾸지 않는다 — 메시지 전송은
   정상 사용자 행위(부수효과=세션/메시지 생성뿐, exposed 플래그 등 설정은 불변).
   템플릿=shot-custom-a2a-154.mjs(로그인·PLAYWRIGHT_DIR 관례), 진입=shot-playground.mjs
   (state 라우팅이라 메뉴 텍스트 'Playground' 클릭으로 진입). antd6 Segmented는
   `.ant-segmented-item`(label 텍스트)이지 버튼이 아니다 — 정확 텍스트 클릭 대신 부모
   `.ant-segmented` 스코프 안에서 label 텍스트로 매칭한다(과거 회고: 커스텀 Drawer는 antd
   아님과 유사하게, Segmented 내부 구조도 버튼이 아니므로 role 기반 클릭을 피한다).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-playground-a2a-155.mjs */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..')
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_DIR = path.join(__dirname, 'out-155')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message))

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

// AgentCombo 트리거는 "현재 선택된" 에이전트 이름을 보여준다(목표 에이전트 이름이 아님) —
// 목표 이름으로 트리거를 찾으면 아직 안 바뀐 상태에선 못 찾는다. 그래서 트리거는 시드
// 에이전트 5종 이름 중 아무거나(현재 활성) 매칭하는 공통 정규식으로 열고, 드롭다운이 열린
// 뒤에만 목표 이름으로 행을 골라 클릭한다.
const ANY_SEED_AGENT_RE = /research-assistant|personal-secretary|doc-translator|acme-translate-a2a|plan-execute-demo/i
async function pickAgent(agentNameSubstr) {
  const trigger = page.getByRole('button', { name: ANY_SEED_AGENT_RE }).first()
  await trigger.waitFor({ timeout: 10000 })
  await trigger.click()
  await page.waitForTimeout(300)
  // 드롭다운 안에서 목표 이름의 행을 클릭(스스로 닫힘 — onSwitch → setOpen(false)).
  const row = page.locator('button', { hasText: new RegExp(agentNameSubstr, 'i') }).last()
  await row.waitFor({ timeout: 10000 })
  await row.click()
  await page.waitForTimeout(500)
}

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- 플레이그라운드 진입(state 라우팅 — 메뉴 텍스트 클릭) ----------
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  // ================= K1: "Research Assistant" 선택 → "직접"/"A2A" Segmented 노출 =================
  await pickAgent('research-assistant')
  const segmented = page.locator('.ant-segmented').filter({ hasText: '직접' }).filter({ hasText: 'A2A' })
  const segmentedShown = await segmented.first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  check(segmentedShown, 'K1: "Research Assistant" 선택 후 헤더에 "직접"/"A2A" Segmented 토글 표시')
  await shot('01-research-assistant-toggle')

  // ================= K2: "A2A" 클릭 → 선택 상태로 전환 =================
  const a2aItem = segmented.locator('.ant-segmented-item', { hasText: 'A2A' }).first()
  await a2aItem.waitFor({ timeout: 5000 })
  await a2aItem.click()
  // 선택 클래스 부착에 CSS thumb 트랜지션 지연이 있어(실측 300ms 불충분) 최대 2초 폴링.
  const a2aSelected = await page
    .waitForFunction(
      () => {
        const items = document.querySelectorAll('.ant-segmented .ant-segmented-item')
        const target = Array.from(items).find((el) => el.textContent?.includes('A2A'))
        return !!target && target.classList.contains('ant-segmented-item-selected')
      },
      { timeout: 2000, polling: 100 },
    )
    .then(() => true)
    .catch(() => false)
  check(a2aSelected, `K2: "A2A" 클릭 후 선택 상태(class=ant-segmented-item-selected)로 전환(실측=${a2aSelected})`)
  await shot('02-a2a-selected')

  // ================= K3: 메시지 전송 → A2A 경유 응답 렌더(최대 60초) =================
  const textarea = page.locator('textarea').first()
  await textarea.waitFor({ timeout: 10000 })
  await textarea.fill('A2A 루프백 스모크')
  await textarea.press('Enter')

  // ai 버블(placement=start) content가 비어있지 않은 텍스트를 담을 때까지 폴링.
  const aiBubbleHasText = await page
    .waitForFunction(
      () => {
        const nodes = document.querySelectorAll('.ant-bubble-start .ant-bubble-content')
        if (nodes.length === 0) return false
        const last = nodes[nodes.length - 1]
        return (last.textContent || '').trim().length > 0
      },
      { timeout: 60000, polling: 500 },
    )
    .then(() => true)
    .catch(() => false)
  check(aiBubbleHasText, 'K3: 전송 후 60초 내 ai 버블에 비어있지 않은 텍스트 렌더(A2A 경유 응답)')
  await page.waitForTimeout(300)
  await shot('03-a2a-response')

  // ================= K4: "Personal Secretary"(미노출) 선택 → A2A 토글 부재 =================
  await pickAgent('personal-secretary')
  const noSegmented = (await page.locator('.ant-segmented').filter({ hasText: '직접' }).filter({ hasText: 'A2A' }).count()) === 0
  check(noSegmented, 'K4: "Personal Secretary"(미노출) 선택 후 헤더에 A2A Segmented 토글 부재')
  await shot('04-personal-secretary-no-toggle')

  const fatalErrors = consoleErrors.filter((e) => /50\d|crash|Uncaught/i.test(e))
  console.log(
    consoleErrors.length
      ? `CONSOLE_ERRORS(${consoleErrors.length}, fatal=${fatalErrors.length}) ` + JSON.stringify(consoleErrors.slice(0, 10))
      : 'NO_CONSOLE_ERRORS',
  )
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
