/* 스펙 320 프론트 기능 검증 — 도구 실행 실패 사유를 인스펙터가 표시(외형 아닌 동작:
   진짜 실패 도구를 호출시켜 trace.mcp[].error 배선 + 인스펙터 "실패 사유" 렌더를 e2e로 단언).
   ① local-tools 서버에 failing_op(의도 실패 mock)를 rediscover+enable(런타임 게이트 통과).
   ② 노드형 에이전트가 failing_op만 바인딩 → 활성화.
   ③ 플레이그라운드에서 "실패" 트리거 문장 전송 → 인스펙터 열기 → "실패 사유"·예외 메시지 노출.
   ④ 백엔드 왕복: 세션 trace.mcp 에 status=error + error(사유 문자열)이 실제로 실렸는지 단언.
   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-320-tool-error-inspector.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()

const sfx = Date.now().toString(36)
const AGENT = `v320-fail-${sfx}`
// 전용 임시 MCP 서버(mock self-host URL을 가리킴) — 공용 local-tools를 건드리지 않아 hermetic·재실행 가능.
const SRV = `v320srv-${sfx}`
const MOCK_MCP_URL = process.env.MOCK_MCP_URL ?? 'http://127.0.0.1:8000/_remote/mcp/'
const FAIL_TOOL = `${SRV}__failing_op`

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]
const api = (path, init = {}) =>
  fetch(`${API}${path}`, { ...init, headers: { 'Content-Type': 'application/json', Cookie: cookie, ...(init.headers || {}) } })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1100 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

let agentId = null
let srvId = null
try {
  // ── ① 전용 임시 MCP 서버 생성(mock URL·failing_op만 enable) — 공용 local-tools 무변경 ──
  const cs = await api('/mcp-servers', {
    method: 'POST',
    body: JSON.stringify({
      name: SRV, source: 'local', transport: 'http', url: MOCK_MCP_URL,
      tools: ['failing_op'], enabled_tools: ['failing_op'],
    }),
  })
  const srv = await cs.json()
  srvId = srv?.id
  check(cs.status === 201 && !!srvId, `① 전용 MCP 서버 생성 (${cs.status}, id=${srvId})`)
  check((srv.enabled_tools || []).includes('failing_op'), `① enabled_tools 에 failing_op 활성 (got ${JSON.stringify(srv.enabled_tools)})`)

  // ── ② 노드형 에이전트(failing_op만 바인딩) 생성 + 활성화 ──
  const cr = await api('/agents', {
    method: 'POST',
    body: JSON.stringify({
      name: AGENT,
      config: {
        model: 'mock-llm', prompt: '', impl: 'pipeline', mcps: [SRV],
        nodes: [{ name: 'n1', prompt: '요청을 처리해라', model: 'mock-llm', tools: [FAIL_TOOL] }],
      },
    }),
  })
  const agent = await cr.json()
  agentId = agent?.id
  const agentBizId = agent?.agentId // agt_ 식별자 — /sessions 필터는 이 값을 받는다(DB uuid 아님)
  check(cr.status === 201 && !!agentId, `② 노드형 생성 (${cr.status}, id=${agentId})`)
  const g = await (await api(`/agents/${agentId}`)).json()
  const draft = (g.versions || []).find((v) => v.status === 'draft')?.version
  if (draft) await api(`/agents/${agentId}/activate`, { method: 'POST', body: JSON.stringify({ version: draft }) })
  const g2 = await (await api(`/agents/${agentId}`)).json()
  check(!!g2.activeVersion, `② 활성 버전 보유 (${g2.activeVersion})`)

  // ── ③ 플레이그라운드 → 전송("실패" 트리거) → 인스펙터 "실패 사유" 노출 ──
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.keyboard.type(AGENT)
  await page.waitForTimeout(600)
  await page.getByText(AGENT, { exact: false }).first().click()
  await page.waitForTimeout(500)
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('일부러 실패시켜줘 (에러 재현)'); await ta.press('Enter')

  // 응답 도착(인스펙터 링크) 대기
  const waitFor = async (re, timeout) => {
    const t0 = Date.now()
    while (Date.now() - t0 < timeout) {
      if (re.test(await page.evaluate(() => document.body.innerText).catch(() => ''))) return true
      await page.waitForTimeout(500)
    }
    return false
  }
  check(await waitFor(/인스펙터/, 30000), '③ 응답 도착(인스펙터 링크)')
  await page.getByText('인스펙터', { exact: false }).last().click()
  await page.waitForTimeout(800)
  const insText = await page.evaluate(() => document.body.innerText)
  check(/실패 사유/.test(insText), '③ 인스펙터에 "실패 사유" 라벨 노출')
  check(/의도된 실패/.test(insText), `③ 인스펙터에 예외 메시지(의도된 실패…) 노출`)

  // ── ④ 백엔드 왕복 — 세션 trace.mcp 에 status=error + error 사유 문자열 ──
  const ss = await (await api(`/sessions?agent_id=${agentBizId}`)).json()
  const sid = ss?.items?.[0]?.id
  const msgs = sid ? await (await api(`/sessions/${sid}/messages`)).json() : []
  const aiTrace = [...msgs].reverse().find((m) => (m.role === 'assistant' || m.role === 'ai') && m.trace)?.trace
  const failCall = (aiTrace?.mcp || []).find((c) => c.tool === 'failing_op' || (c.tool || '').includes('failing_op'))
  check(failCall?.status === 'error', `④ trace.mcp 에 failing_op status=error (got ${failCall?.status})`)
  check(typeof failCall?.error === 'string' && /의도된 실패/.test(failCall.error),
    `④ trace.mcp[].error 에 사유 문자열 (got ${JSON.stringify(failCall?.error)?.slice(0, 120)})`)

  check(pageErrors.length === 0, `페이지 JS 에러 0 (got ${pageErrors.slice(0, 2)})`)
} finally {
  if (agentId) await api(`/agents/${agentId}`, { method: 'DELETE' }).catch(() => {})
  if (srvId) await api(`/mcp-servers/${srvId}`, { method: 'DELETE' }).catch(() => {}) // 임시 서버 정리(hermetic)
  await browser.close()
}

console.log(`\n${fails.length} failed`)
if (fails.length) { for (const f of fails) console.log('  FAILED:', f); process.exit(1) }
console.log('VERIFY320_UI_OK — 도구 실패 사유(진짜 실패 도구 호출→trace.error 배선→인스펙터 "실패 사유" 렌더) 기능 정착')
