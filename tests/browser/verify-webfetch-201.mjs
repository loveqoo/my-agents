/* 스펙 201 e2e — web-fetch 커스텀 MCP 등록·서빙·능력 부여 표면(모델/외부망 비의존 회귀).
   ① reconcile 등록(행·도구 2종·custom) ② 서빙 initialize 200(published) ③ 능력 부여 카탈로그에
   web-fetch 노출 ④ member 부여 목록 표시(도그푸딩 잔존 확인). 위키 실호출은 verify_201(단위+live
   스모크)·플레이그라운드 실검증(스샷)이 담당.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-webfetch-201.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]

// ① 등록(reconcile) — 행·source·도구
const rowsRes = await fetch(`${API}/mcp-servers`, { headers: { Cookie: cookie } })
ok(rowsRes.status === 200, `1a /mcp-servers 200 (실제 ${rowsRes.status} — 오염 행 500 회귀 감시)`)
const rows = rowsRes.status === 200 ? await rowsRes.json() : []
const wf = rows.find((r) => r.name === 'web-fetch')
ok(!!wf && wf.source === 'custom', '1b web-fetch 행(custom) 존재')
ok(wf && new Set(wf.tools).size === 2 && wf.tools.includes('wiki_search') && wf.tools.includes('wiki_page'),
  `1c 도구 2종(wiki_search·wiki_page) (실제 ${wf?.tools})`)

// ② 서빙(published 전제 — 도그푸딩에서 공개함)
if (wf?.published) {
  const init = await fetch(`${API}/_served/mcp/web-fetch/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'verify', version: '0' } } }),
  })
  ok(init.status === 200, `2 서빙 initialize 200 (실제 ${init.status})`)
} else {
  ok(true, '2 미공개 상태 — 서빙 검사 스킵(공개는 관리자 선택)')
}

// ③④ UI — 능력 부여 카탈로그·부여 목록
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('유저', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.getByRole('tab', { name: '능력 부여' }).click()
  await page.waitForTimeout(700)
  const pane = page.locator('.ant-tabs-tabpane-active').first()
  // 종류=도구 → 카탈로그에 web-fetch
  await pane.locator('.ant-select').nth(1).click()
  await page.waitForTimeout(400)
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')
    .filter({ hasText: '도구 (MCP 서버)' }).first().click()
  await page.waitForTimeout(500)
  await pane.locator('.ant-select').nth(2).click()
  await page.waitForTimeout(500)
  const opts = await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').allInnerTexts()
  ok(opts.some((t) => t.includes('web-fetch')), `3 도구 카탈로그에 web-fetch (옵션 ${opts.length}개)`)
  await page.keyboard.press('Escape')
  // 부여 목록(도그푸딩 잔존): member → 도구 · web-fetch
  const bt = await page.locator('body').innerText()
  ok(bt.includes('도구 · web-fetch'), '4 member 부여 목록에 도구 · web-fetch')
  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (WEBFETCH201_E2E_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
