/* 스펙 153 e2e — A2A organization 설정(SettingsView) 브라우저 검증.
   (K1) 관리자 그룹 → '설정' 클릭 → "A2A organization" 텍스트 + 입력창(현재 값 "my-agents").
   (K2) 값을 "e2e-org-153"으로 바꿔 저장 → 성공 토스트 → 다른 메뉴로 갔다가 '설정' 재진입 →
        입력창 값이 "e2e-org-153"으로 유지(무재시작 반영 확인).
   (K3) 원복(중요) — 값을 "my-agents"로 되돌려 저장 → 재진입 후 "my-agents" 확인
        → 마지막에 curl로 GET /admin/settings(Authorization Bearer=API_AUTH_TOKEN)을 실측해
        a2a_org_name=="my-agents" 증명(DB 실측, UI 재조회 아님).
   (K4) 빈 값 저장 시도 → 경고 메시지("organization 이름을 입력하세요") 표시, 저장 API 호출 안 됨
        (네트워크 요청 감시로 PUT 미발생을 확인 — 토스트만으론 "저장 안 됨"을 증명 못 하므로).

   템플릿=shot-mcp-detail-151.mjs(로그인·대기 관례), 메뉴 클릭 패턴=shot-admin-menu-065.mjs
   ('.ant-layout-header h3'로 뷰 타이틀 확인, 관리자 그룹 항목은 텍스트 클릭).
   앱 코드 수정 없음 — 검증 전용. K3에서 원값으로 반드시 되돌리고 실측까지 완료해야 종료.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-settings-153.mjs */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execSync } from 'node:child_process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..')
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API_URL = process.env.API_URL ?? 'http://127.0.0.1:8000'
const OUT_DIR = path.join(__dirname, 'out-153')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

// .env에서 API_AUTH_TOKEN 실측(하드코딩 금지 — 값이 바뀌어도 스크립트가 따라간다).
const envText = fs.readFileSync(path.join(REPO, '.env'), 'utf8')
const tokenMatch = envText.match(/^API_AUTH_TOKEN=(.+)$/m)
const API_TOKEN = process.env.API_AUTH_TOKEN ?? (tokenMatch ? tokenMatch[1].trim() : '')

const ORIG_VALUE = 'my-agents'
const NEW_VALUE = 'e2e-org-153'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

function fetchSettings() {
  const out = execSync(
    `curl -s ${API_URL}/admin/settings -H "Authorization: Bearer ${API_TOKEN}"`,
    { encoding: 'utf8' }
  )
  return JSON.parse(out)
}

// '설정' 메뉴로 진입 — 관리자 그룹 항목 텍스트 클릭 → 헤더 타이틀 '설정' 확인 → 입력창 대기.
async function openSettings() {
  await page.getByText('설정', { exact: true }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '설정' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

const orgInput = () => page.getByPlaceholder('예: acme-lab')

let reachedK3Restore = false

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ================= K1: 관리자 그룹 → '설정' → "A2A organization" + 입력창 값 "my-agents" =================
  await openSettings()
  await shot('00-settings-initial')
  const bodyText1 = await page.locator('body').innerText()
  const inputVal1 = await orgInput().inputValue()
  check(bodyText1.includes('A2A organization'), 'K1a: "A2A organization" 텍스트 표시')
  check(inputVal1 === ORIG_VALUE, `K1b: 입력창 현재 값="${ORIG_VALUE}"(실측="${inputVal1}")`)

  // ================= K2: 값을 "e2e-org-153"으로 바꿔 저장 → 성공 토스트 → 재진입 후 값 유지 =================
  await orgInput().fill('')
  await orgInput().fill(NEW_VALUE)
  await page.getByRole('button', { name: '저장' }).click()
  const saveToast1 = page.locator('.ant-message-success', { hasText: '저장했습니다' })
  const toastShown1 = await saveToast1.last().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  check(toastShown1, 'K2a: 성공 토스트 "저장했습니다 — A2A 카드에 즉시 반영됩니다(재시작 불요)" 표시')
  await shot('k2-saved-toast')

  // 다른 메뉴로 갔다가 '설정' 재진입.
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
  await openSettings()
  const inputVal2 = await orgInput().inputValue()
  check(inputVal2 === NEW_VALUE, `K2b: 재진입 후 입력창 값="${NEW_VALUE}" 유지(실측="${inputVal2}")`)
  await shot('k2-after-reentry')

  // ================= K3: 원복 — "my-agents"로 되돌려 저장 → 재진입 확인 → curl 실측 =================
  reachedK3Restore = true
  await orgInput().fill('')
  await orgInput().fill(ORIG_VALUE)
  await page.getByRole('button', { name: '저장' }).click()
  const saveToast2 = page.locator('.ant-message-success', { hasText: '저장했습니다' })
  const toastShown2 = await saveToast2.last().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  check(toastShown2, 'K3a: 원복 저장 성공 토스트 표시')
  reachedK3Restore = false // 저장 API 호출까지 도달 — 아래 curl 실측이 최종 확인

  await page.getByText('에이전트', { exact: true }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
  await openSettings()
  const inputVal3 = await orgInput().inputValue()
  check(inputVal3 === ORIG_VALUE, `K3b: 재진입 후 입력창 값="${ORIG_VALUE}" 확인(실측="${inputVal3}")`)
  await shot('k3-restored')

  // curl 실측 — API_AUTH_TOKEN Bearer로 DB 원본 값을 직접 확인(UI 재조회가 아닌 서버 실측).
  const settingsAfterRestore = fetchSettings()
  check(
    settingsAfterRestore.a2a_org_name === ORIG_VALUE,
    `K3c: curl GET /admin/settings 실측 a2a_org_name="${ORIG_VALUE}"(실측=${JSON.stringify(settingsAfterRestore)})`
  )

  // ================= K4: 빈 값 저장 시도 → 경고 메시지, 저장 API(PUT) 호출 안 됨 =================
  const putRequests = []
  page.on('request', (req) => {
    if (req.method() === 'PUT' && req.url().includes('/admin/settings/')) putRequests.push(req.url())
  })
  await orgInput().fill('')
  await page.getByRole('button', { name: '저장' }).click()
  const warnToast = page.locator('.ant-message-warning', { hasText: 'organization 이름을 입력하세요' })
  const warnShown = await warnToast.last().waitFor({ timeout: 5000 }).then(() => true).catch(() => false)
  check(warnShown, 'K4a: 경고 메시지 "organization 이름을 입력하세요" 표시')
  await page.waitForTimeout(500)
  check(putRequests.length === 0, `K4b: 빈 값 저장 시도 시 PUT /admin/settings 호출 안 됨(실측 호출 수=${putRequests.length})`)
  await shot('k4-empty-warning')

  // 빈 값으로 남기지 않도록 입력창을 원값으로 되돌려 화면 상태 정리(저장은 이미 K3에서 완료·DB엔 영향 없음).
  await orgInput().fill(ORIG_VALUE)

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
  if (reachedK3Restore) {
    console.error('경고: K3 원복 저장 시도 중 예외 — DB 상태 미확정. curl로 즉시 수동 확인 필요.')
  }
} finally {
  // 종료 직전 안전망 — 어떤 경로로든 원복이 안 됐다면 curl 실측으로 감지하고 API로 강제 원복 시도.
  try {
    const finalCheck = fetchSettings()
    if (finalCheck.a2a_org_name !== ORIG_VALUE) {
      console.error(`경고: 종료 시점 DB 값이 원본이 아님(실측=${JSON.stringify(finalCheck)}) — 강제 원복 시도`)
      execSync(
        `curl -s -X PUT ${API_URL}/admin/settings/a2a_org_name -H "Authorization: Bearer ${API_TOKEN}" -H "Content-Type: application/json" -d '{"value":"${ORIG_VALUE}"}'`,
        { encoding: 'utf8' }
      )
      const reCheck = fetchSettings()
      check(reCheck.a2a_org_name === ORIG_VALUE, `안전망 원복 재확인(실측=${JSON.stringify(reCheck)})`)
    }
  } catch (e2) {
    console.error('안전망 원복 확인 실패', e2.message)
    fails.push('안전망 원복 확인 실패: ' + e2.message)
  }
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
