/* 스펙 156 e2e — 커스텀(SDK) MCP `calc-tools` 외부 공개(MCP 서빙) 브라우저 검증.
   (K1) 빌딩 블록 → MCP 탭 → `calc-tools` 행에 "커스텀" 배지가 보인다.
   (K2) `calc-tools` 행 클릭 → 상세 드로어에 "외부 공개" 섹션 + Switch(꺼짐) +
        "공개하면 외부가 이 URL로 등록·접속합니다" 안내(served_url `/_served/mcp/calc-tools/` 포함).
   (K3) "외부 공개" Switch를 켠다 → public 태그 + 서빙 URL code + 복사 버튼이 나타난다.
   (K4) 원복 필수 — Switch를 다시 꺼서 published=False로 되돌린다. 스크립트 끝에서
        curl PUT /mcp-servers/{id}/publish {published:false}로 강제 원복하고,
        curl GET /blocks로 calc-tools published==false를 실측 확인한다.

   템플릿=shot-mcp-detail-151.mjs(로그인·대기 관례·빌딩 블록/MCP 탭 진입),
   원복 안전망=shot-custom-a2a-154.mjs(사전/사후 curl 실측 + finally 강제 원복).
   앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-custom-mcp-156.mjs */
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
const OUT_DIR = path.join(__dirname, 'out-156')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

// .env에서 API_AUTH_TOKEN 실측(하드코딩 금지 — 값이 바뀌어도 스크립트가 따라간다).
const envText = fs.readFileSync(path.join(REPO, '.env'), 'utf8')
const tokenMatch = envText.match(/^API_AUTH_TOKEN=(.+)$/m)
const API_TOKEN = process.env.API_AUTH_TOKEN ?? (tokenMatch ? tokenMatch[1].trim() : '')

const SERVED_URL = `${API_URL}/_served/mcp/calc-tools/`

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

function fetchBlocks() {
  const out = execSync(
    `curl -s ${API_URL}/blocks -H "Authorization: Bearer ${API_TOKEN}"`,
    { encoding: 'utf8' }
  )
  return JSON.parse(out)
}

function findCalcTools(blocks) {
  const items = blocks?.mcp?.items ?? []
  return items.find((i) => i.name === 'calc-tools')
}

function forcePublish(id, published) {
  return execSync(
    `curl -s -X PUT ${API_URL}/mcp-servers/${id}/publish -H "Authorization: Bearer ${API_TOKEN}" -H "Content-Type: application/json" -d '{"published": ${published}}'`,
    { encoding: 'utf8' }
  )
}

let calcToolsId = null
let reachedMutation = false

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 사전 실측 — id 확보 + 시작 전 published 상태 기록.
  const preBlocks = fetchBlocks()
  const preCalc = findCalcTools(preBlocks)
  calcToolsId = preCalc?.id
  check(!!preCalc, `사전 실측: calc-tools 블록 존재(id=${calcToolsId})`)
  check(preCalc?.published === false, `사전 실측: calc-tools 시작 상태 published=false(실측=${preCalc?.published})`)

  // ---------- 빌딩 블록 → MCP 탭 ----------
  await page.getByText('빌딩 블록', { exact: true }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '빌딩 블록' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
  await page.getByRole('tab', { name: /MCP/ }).click()
  await page.waitForTimeout(600)

  // ================= K1: calc-tools 행 → "커스텀" 배지 =================
  const calcRow = page.locator('tr', { hasText: 'calc-tools' }).first()
  await calcRow.waitFor({ timeout: 10000 })
  const calcRowText = await calcRow.innerText()
  const calcRowBadgeOk = calcRowText.includes('커스텀')
  check(calcRowBadgeOk, `K1: calc-tools 행에 "커스텀" 배지 표시(발췌="${calcRowText.replace(/\n/g, ' | ')}")`)
  await shot('k1-mcp-list-calc-tools')

  // ================= K2: 행 클릭 → 드로어 "외부 공개" 섹션 + Switch(꺼짐) + 안내 문구 =================
  await calcRow.click()
  await page.waitForTimeout(600)
  const bodyText1 = await page.locator('body').innerText()
  check(bodyText1.includes('외부 서빙'), 'K2a: "외부 서빙" 섹션 표시')
  const publishSwitch = page.locator('.ant-switch').last()
  const switchCount = await publishSwitch.count()
  const ariaChecked = switchCount > 0 ? await publishSwitch.getAttribute('aria-checked').catch(() => null) : null
  check(switchCount > 0 && ariaChecked === 'false', `K2b: 외부 공개 Switch 꺼짐 상태 표시(실측 aria-checked=${ariaChecked})`)
  const noticeOk = bodyText1.includes('공개하면 외부가 이 URL로 등록·접속합니다') && bodyText1.includes('/_served/mcp/calc-tools/')
  check(noticeOk, `K2c: 미공개 안내 문구 + served_url 경로 표시(실측 served_url 포함 여부=${bodyText1.includes('/_served/mcp/calc-tools/')})`)
  await shot('k2-drawer-unpublished')

  // ================= K3: Switch를 켠다 → public 태그 + 서빙 URL + 복사 버튼 =================
  reachedMutation = true
  await publishSwitch.click()
  await page.waitForTimeout(800)
  const bodyText2 = await page.locator('body').innerText()
  check(bodyText2.includes('공개'), 'K3a: "공개" 태그 표시')
  check(bodyText2.includes(SERVED_URL), `K3b: 서빙 URL 표시(실측 포함 여부=${bodyText2.includes(SERVED_URL)}, url=${SERVED_URL})`)
  const copyBtnCount = await page.locator('button[class*="ant-btn"] .anticon-copy, button:has(.anticon-copy)').count()
  check(copyBtnCount > 0, `K3c: 복사 버튼 표시(실측 개수=${copyBtnCount})`)
  const ariaCheckedAfter = await publishSwitch.getAttribute('aria-checked').catch(() => null)
  check(ariaCheckedAfter === 'true', `K3d: Switch 켜짐 상태로 반영(실측 aria-checked=${ariaCheckedAfter})`)
  await shot('k3-drawer-published')

  // ================= K4: Switch를 다시 꺼서 원복 =================
  await publishSwitch.click()
  await page.waitForTimeout(800)
  const bodyText3 = await page.locator('body').innerText()
  const ariaCheckedRestored = await publishSwitch.getAttribute('aria-checked').catch(() => null)
  check(ariaCheckedRestored === 'false', `K4a: Switch UI로 다시 끔(실측 aria-checked=${ariaCheckedRestored})`)
  check(bodyText3.includes('공개하면 외부가 이 URL로 등록·접속합니다'), 'K4b: 미공개 안내 문구 복귀')
  await shot('k4-drawer-restored')
  reachedMutation = false // UI로 원복 시도 완료 — 아래 curl 실측 + 강제 원복이 최종 확인

  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
  if (reachedMutation) {
    console.error('경고: 원복 전 예외 발생 — DB 상태 미확정. 안전망에서 강제 원복 시도.')
  }
} finally {
  // 종료 직전 안전망 — 실측으로 원복 상태를 감지하고, 어긋나면 API로 강제 원복(curl PUT publish false).
  try {
    if (calcToolsId) {
      forcePublish(calcToolsId, false)
    }
    const finalBlocks = fetchBlocks()
    const finalCalc = findCalcTools(finalBlocks)
    check(!!finalCalc && finalCalc.published === false, `원복 실측: curl GET /blocks calc-tools published==false(실측=${finalCalc?.published})`)
  } catch (e2) {
    console.error('안전망 원복 확인 실패', e2.message)
    fails.push('안전망 원복 확인 실패: ' + e2.message)
  }
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
