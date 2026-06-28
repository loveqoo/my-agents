/* 스펙 054 P2 검증 스크린샷 — MCP 등록 폼의 라이브 도구 탐색(연결 테스트→자동채움).
   admin(vite :5173) 로그인 후:
   (1) 빌딩 블록 → MCP 서버 탭 → "외부 등록" → 외부 MCP 등록 모달.
   (2) MCP URL에 self-host mock(/_remote/mcp/) 입력 → "연결 테스트" 클릭 →
       서버가 실제로 응답한 도구 web_search/echo/delete_record가 체크박스로 자동채움(부작용 0).
   (3) URL을 사설대역(10.x)으로 바꿔 다시 "연결 테스트" → SSRF 차단 에러 알림(자동채움 안 됨).
   데이터는 라이브 백엔드 /mcp-servers/discover에서 옴 — 실연결의 시각 증명.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-mcp-discover-054.mjs /tmp/mcp054 */
import { provisionSuper } from './_fixture.mjs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/mcp054'
const MOCK_URL = 'http://127.0.0.1:8000/_remote/mcp/'

// ADMIN_EMAIL 오버라이드가 없으면 던짐용 super를 즉석 시드(프로세스 종료 시 자동 삭제).
let EMAIL = process.env.ADMIN_EMAIL
let PASSWORD = process.env.ADMIN_PASSWORD
if (!EMAIL) {
  const fx = provisionSuper()
  EMAIL = fx.email
  PASSWORD = fx.password
}

const EXPECT_TOOLS = ['web_search', 'echo', 'delete_record']
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()

async function present(name) {
  return (await page.getByText(name, { exact: true }).count()) > 0
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // (1) 빌딩 블록 → MCP 서버 탭 → 외부 등록
  await page.getByText('빌딩 블록', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.getByRole('tab', { name: /MCP/ }).click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: '외부 등록' }).click()
  await page.getByText('외부 MCP 등록', { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(400)

  // (2) URL 입력 → 연결 테스트 → 자동채움
  await page.getByPlaceholder('예: partner-crm').fill('mock-local-tools')
  await page.getByPlaceholder('mcp://host/endpoint').fill(MOCK_URL)
  await page.screenshot({ path: `${OUT}-1-before-discover.png`, fullPage: true })
  await page.getByRole('button', { name: '연결 테스트' }).click()
  // 자동채움 대기: "도구 발견" 성공 알림 또는 체크박스 등장.
  await page.getByText(/도구 발견/).waitFor({ timeout: 15000 })
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${OUT}-2-discovered.png`, fullPage: true })
  for (const t of EXPECT_TOOLS) ok(await present(t), `탐색 자동채움: ${t} 체크박스 표시`)
  ok((await page.getByText(/3개 도구 발견/).count()) > 0, '성공 알림: "3개 도구 발견" 표시')

  // (3) 사설대역 URL → SSRF 차단 에러(자동채움 안 됨)
  await page.getByPlaceholder('mcp://host/endpoint').fill('http://10.1.2.3:9000/mcp/')
  await page.getByRole('button', { name: '연결 테스트' }).click()
  await page.getByText(/차단되었거나 도달할 수 없는/).waitFor({ timeout: 15000 })
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}-3-ssrf-blocked.png`, fullPage: true })
  ok(await present('연결 실패 — 차단되었거나 도달할 수 없는 주소입니다.'), 'SSRF 차단 에러 알림 표시')

  console.log('')
  if (fails.length) { console.log(`검증 실패 ${fails.length}건`); process.exitCode = 1 }
  else console.log('스펙 054 P2 브라우저 검증 — 전부 통과.')
} catch (e) {
  console.error('SHOT ERROR:', e.message)
  process.exitCode = 2
} finally {
  await browser.close()
}
