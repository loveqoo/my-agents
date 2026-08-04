/* 스펙 318 후속 — 플레이그라운드 오버라이드에 에이전트 picker 정합(외형 아닌 기능: 선택→override payload 단언).
   318이 본 폼에만 picker를 붙이고 OverridePanel엔 안 붙였던 갭 봉합. 백엔드는 이미 준비(tools 오버라이드
   허용·derive_pipeline_pool이 로드 시 capabilities 재파생) — 프론트 picker만 배선.
   ① 오버라이드 드로어(노드형)에 "에이전트 (선택)" picker 노출(본 폼과 대칭).
   ② 후보 스코프: 위임 대상(expert) 있음·자기 자신(현재 에이전트) 없음.
   ③ 기능 왕복: expert 선택 → 적용 → POST /chat body.overrides.nodes[0].tools 에 `agent__{expertId}` 배선.
   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-318-override-agent-picker.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const sfx = Date.now().toString(36)
const EXPERT = 'ov318-expert-' + sfx
const PIPE = 'ov318-pipe-' + sfx
const cleanup = { agents: [] }
const apiPost = (path, data) => page.request.post(`${URL}/api${path}`, { data })
const apiGet = (path) => page.request.get(`${URL}/api${path}`)
const apiDel = (path) => page.request.delete(`${URL}/api${path}`)

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // expert(위임 대상) — ui 로컬, 활성 버전 보유(위임 자격).
  const er = await apiPost('/agents', { name: EXPERT, config: { model: 'mock-llm', prompt: '너는 전문가다.' } })
  const expert = await er.json()
  check(er.ok() && !!expert?.id, `expert 생성 (${er.status()}, id=${expert?.id})`)
  if (expert?.id) cleanup.agents.push(expert.id)
  const expertAgentId = expert.agentId
  const eg = await (await apiGet(`/agents/${expert.id}`)).json()
  const draft = (eg.versions || []).find((v) => v.status === 'draft')?.version
  if (draft) await apiPost(`/agents/${expert.id}/activate`, { version: draft })

  // 노드형(에이전트 도구 없이 시작) — n1은 MCP 도구만.
  const pr = await apiPost('/agents', { name: PIPE, config: { model: 'mock-llm', prompt: '', impl: 'pipeline',
    mcps: ['local-tools'],
    nodes: [{ name: 'n1', prompt: '분석해라', model: 'mock-llm', tools: ['local-tools__echo'] }] } })
  const pipe = await pr.json()
  check(pr.ok() && !!pipe?.id, `노드형 생성 (${pr.status()}, id=${pipe?.id})`)
  if (pipe?.id) cleanup.agents.push(pipe.id)

  // Playground → 에이전트 picker(검색으로 필터 — 목록이 길어 스크롤 대신 타이핑) → 노드형 선택
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(500)
  await page.keyboard.type(PIPE)
  await page.waitForTimeout(700)
  await page.getByText(PIPE, { exact: false }).first().click()
  await page.waitForTimeout(600)
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')

  // 노드 n1 펼침
  await drawer.locator('.ant-collapse-expand-icon').first().click()
  await page.waitForTimeout(500)

  // ── ① "에이전트 (선택)" picker 노출 ──
  const drawerText = await drawer.innerText()
  check(/에이전트 \(선택\)/.test(drawerText), '① 오버라이드 드로어에 "에이전트 (선택)" picker 노출')

  // ── ② 후보 스코프 — picker 열기 ──
  const agentField = drawer.getByText('에이전트 (선택)', { exact: true })
    .locator('xpath=following-sibling::div[contains(@class,"ant-select")]').first()
  await agentField.scrollIntoViewIfNeeded()
  await agentField.click()
  await page.waitForTimeout(500)
  const dropText = await page.locator('.ant-select-dropdown:visible').last().innerText()
  check(dropText.includes(EXPERT), `② picker 후보에 expert (got ${JSON.stringify(dropText.slice(0, 120))})`)
  check(!dropText.includes(PIPE), '② picker 후보에 자기 자신(현재 에이전트) 없음')

  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: EXPERT }).first().click()
  await page.waitForTimeout(400)
  // 드롭다운 닫기(모달 유지) — 프롬프트 textarea 클릭으로 blur
  await drawer.locator('textarea').first().click()
  await page.waitForTimeout(300)

  // ── ③ 적용 → POST /chat overrides.nodes[0].tools 에 agent 도구 배선 ──
  await drawer.getByRole('button', { name: /적용 — 새 대화/ }).click()
  await page.waitForTimeout(800)

  let chatBody = null
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/agents\/[^/]+\/chat/.test(req.url())) {
      try { chatBody = JSON.parse(req.postData() ?? 'null') } catch {}
    }
  })
  const box = page.locator('textarea').first()
  await box.fill('안녕')
  await box.press('Enter')
  await page.waitForTimeout(2500)

  const ov = chatBody?.overrides ?? null
  const agentTool = `agent__${expertAgentId}`
  log('CHAT_BODY.overrides.nodes[0].tools=' + JSON.stringify(ov?.nodes?.[0]?.tools ?? null))
  check(Array.isArray(ov?.nodes?.[0]?.tools) && ov.nodes[0].tools.includes(agentTool),
    `③ overrides.nodes[0].tools 에 ${agentTool} 배선 (got ${JSON.stringify(ov?.nodes?.[0]?.tools)})`)
  check(Array.isArray(ov?.nodes?.[0]?.tools) && ov.nodes[0].tools.includes('local-tools__echo'),
    '③ 기존 MCP 도구 보존(병합)')

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'VERIFY318_OVERRIDE_OK'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await apiDel(`/agents/${id}`) } catch {} }
  await browser.close()
}
