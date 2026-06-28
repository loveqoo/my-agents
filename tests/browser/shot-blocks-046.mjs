/* 스펙 046 검증 스크린샷 — 빌딩블록 재료 정리 후 카탈로그가 줄었는지 시각 + 텍스트 단언.
   admin(vite :5173) 로그인 후:
   (1) 빌딩 블록 → 권한 탭: web.search/calendar.rw/mail.send만(3), 코드/인프라 권한 부재
   (2) 빌딩 블록 → MCP 서버 탭: tavily/gcal/gmail/notion/acme-weather/partner-crm(6), 코드/인프라 MCP 부재
   (3) 에이전트 목록: Code Reviewer·Ops Copilot 부재, Research·Personal Secretary 존재
   데이터는 백엔드(getBlocks/listAgents)에서 오므로 라이브 DB 정리 결과를 그대로 반영.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-blocks-046.mjs /tmp/blocks046 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/blocks046'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const KEEP_PERMS = ['web.search', 'calendar.rw', 'mail.send']
const GONE_PERMS = ['files.read', 'repo.read', 'repo.merge', 'k8s.read', 'k8s.write']
const KEEP_MCPS = ['tavily', 'gcal', 'gmail', 'notion', 'acme-weather', 'partner-crm']
const GONE_MCPS = ['filesystem', 'github', 'prometheus', 'kubernetes']
const GONE_AGENTS = ['Code Reviewer', 'Ops Copilot']
const KEEP_AGENTS = ['Research Assistant', 'Personal Secretary']

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

  // (1) 빌딩 블록 → 권한 탭
  await page.getByText('빌딩 블록', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.getByRole('tab', { name: /권한/ }).click()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}-1-permissions.png`, fullPage: true })
  for (const p of KEEP_PERMS) ok(await present(p), `권한 유지: ${p} 표시`)
  for (const p of GONE_PERMS) ok(!(await present(p)), `권한 제거: ${p} 부재`)

  // (2) MCP 서버 탭
  await page.getByRole('tab', { name: /MCP/ }).click()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}-2-mcp.png`, fullPage: true })
  for (const m of KEEP_MCPS) ok(await present(m), `MCP 유지: ${m} 표시`)
  for (const m of GONE_MCPS) ok(!(await present(m)), `MCP 제거: ${m} 부재`)

  // (3) 에이전트 목록
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-3-agents.png`, fullPage: true })
  for (const a of KEEP_AGENTS) ok(await present(a), `에이전트 유지: ${a} 표시`)
  for (const a of GONE_AGENTS) ok(!(await present(a)), `에이전트 제거: ${a} 부재`)

  console.log('')
  if (fails.length) { console.log(`검증 실패 ${fails.length}건`); process.exitCode = 1 }
  else console.log('스펙 046 브라우저 검증 — 전부 통과.')
} catch (e) {
  console.error('SHOT ERROR:', e.message)
  process.exitCode = 2
} finally {
  await browser.close()
}
