/* 스펙 151 e2e — MCP 도구 상세 정보(도구 카드·파라미터·재탐색) 브라우저 검증.
   (K1) 빌딩 블록 → MCP 탭 → local-tools 행 클릭 → 상세 드로어에 "도구 3개" + 도구 카드 3장.
   (K2) web_search 카드: 설명("웹을 검색해" 포함) + 파라미터 행(query · string · "필수" 태그).
   (K3) "도구 정보 새로 탐색" 버튼 클릭 → 성공 토스트 → 카드 3장 유지 + web_search 설명 유지
        (라이브 재탐색이 mock 서버 docstring으로 다시 채움 — 무해).
   (K4) 등록 폼 회귀: "외부 등록" 버튼 → "외부 MCP 등록" 모달(식별 이름/별명 필드 존재) → 취소(생성 안 함).

   템플릿=shot-default-model-150.mjs(로그인·대기 관례), 셀렉터 참고=shot-mcp-discover-054.mjs
   (탭 role=/MCP/, 등록 버튼="외부 등록", 모달 제목="외부 MCP 등록", 취소="취소").
   앱 코드 수정 없음 — 검증 전용. 데이터 변형 없음(재탐색은 같은 mock 정의로 재충전).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-mcp-detail-151.mjs */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_DIR = path.join(__dirname, 'out-151')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

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

// 상세 드로어는 커스텀 컴포넌트(shared.tsx Drawer)라 antd 클래스가 없다 — inline style div라
// 안정적인 CSS 앵커가 없어 page 전체를 스코프로 쓴다(배경 목록엔 카드 설명/파라미터 텍스트가
// 없어 "도구 3개"·"웹을 검색해"·"필수" 등은 드로어가 열려야만 나타나므로 혼동 없음).
const drawer = () => page.locator('body')

// 도구 카드 하나 — 도구 이름 code(정확히 일치)에서 카드 div까지 2단계 상향(code→이름행div→카드div).
// (구조: 카드div > 이름행div > code) filter({has:...})는 조상 전부가 매치돼 "" 최소 카드만 못 골라
// xpath ancestor로 정확히 지목한다.
const toolCard = (toolName) =>
  page.locator('code', { hasText: new RegExp(`^${toolName}$`) }).locator('xpath=ancestor::div[2]')

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- 빌딩 블록 → MCP 탭 ----------
  await page.getByText('빌딩 블록', { exact: true }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '빌딩 블록' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
  await page.getByRole('tab', { name: /MCP/ }).click()
  await page.waitForTimeout(600)
  await shot('00-mcp-list')

  // ================= K1: local-tools 행 클릭 → 드로어 "도구 3개" + 카드 3장 =================
  await page.getByText('local-tools', { exact: true }).first().click()
  await drawer().getByText('도구 3개', { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(400)

  const cardCount1 = await drawer().locator('code', { hasText: /^(web_search|echo|delete_record)$/ }).count()
  const drawerText1 = await drawer().innerText()
  check(
    drawerText1.includes('도구 3개') && cardCount1 === 3,
    `K1: 드로어에 "도구 3개" 텍스트 + 도구 카드 3장(코드 태그 개수=${cardCount1})`
  )
  await shot('k1-drawer-tools')

  // ================= K2: web_search 카드 — 설명 + 파라미터(query·string·필수) =================
  const webSearchCard = toolCard('web_search')
  const webSearchCardCount = await webSearchCard.count()
  const webSearchText = webSearchCardCount > 0 ? await webSearchCard.first().innerText() : ''
  const k2DescOk = webSearchText.includes('웹을 검색해')
  const k2ParamOk = webSearchText.includes('query') && webSearchText.includes('string') && webSearchText.includes('필수')
  check(
    webSearchCardCount > 0 && k2DescOk,
    `K2a: web_search 카드에 설명("웹을 검색해" 포함) 표시(실측="${webSearchText.replace(/\n/g, ' | ')}")`
  )
  check(
    webSearchCardCount > 0 && k2ParamOk,
    `K2b: web_search 카드에 파라미터 행(query·string·"필수" 태그) 표시`
  )
  await shot('k2-web-search-card')

  // ================= K3: "도구 정보 새로 탐색" → 성공 토스트 → 카드 3장/설명 유지 =================
  await drawer().getByRole('button', { name: '도구 정보 새로 탐색' }).click()
  const rediscoverToast = page.locator('.ant-message-success', { hasText: '도구 정보를 새로 탐색했습니다' })
  const toastShown = await rediscoverToast.last().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  check(toastShown, 'K3a: 성공 토스트 "도구 정보를 새로 탐색했습니다" 표시')
  await page.waitForTimeout(700)

  await drawer().getByText('도구 3개', { exact: true }).waitFor({ timeout: 8000 }).catch(() => {})
  const cardCount2 = await drawer().locator('code', { hasText: /^(web_search|echo|delete_record)$/ }).count()
  const drawerText2 = await drawer().innerText()
  check(
    drawerText2.includes('도구 3개') && cardCount2 === 3,
    `K3b: 재탐색 후에도 "도구 3개" + 카드 3장 유지(코드 태그 개수=${cardCount2})`
  )

  const webSearchCardAfter = toolCard('web_search')
  const webSearchCardAfterCount = await webSearchCardAfter.count()
  const webSearchTextAfter = webSearchCardAfterCount > 0 ? await webSearchCardAfter.first().innerText() : ''
  check(
    webSearchCardAfterCount > 0 && webSearchTextAfter.includes('웹을 검색해'),
    `K3c: 재탐색 후 web_search 설명 유지(실측="${webSearchTextAfter.replace(/\n/g, ' | ')}")`
  )
  await shot('k3-rediscovered')

  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // ================= K4: 등록 폼 회귀 — "외부 등록" → 모달 → 필드 존재 확인 → 취소 =================
  await page.getByRole('button', { name: '외부 등록' }).click()
  await page.getByText('외부 MCP 등록', { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(400)
  const modalText = await page.locator('.ant-modal').innerText()
  const k4FieldsOk = modalText.includes('식별 이름') && modalText.includes('별명')
  check(k4FieldsOk, `K4a: 등록 모달에 "식별 이름"/"별명" 필드 존재(발췌="${modalText.slice(0, 120).replace(/\n/g, ' | ')}")`)
  await shot('k4-register-modal')

  await page.getByRole('button', { name: '취소' }).click()
  const modalClosed = await page.getByText('외부 MCP 등록', { exact: true }).waitFor({ state: 'hidden', timeout: 5000 }).then(() => true).catch(() => false)
  check(modalClosed, 'K4b: 취소 클릭 후 모달 닫힘(생성 안 함)')
  await shot('k4-after-cancel')

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
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
