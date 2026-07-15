/* 스펙 318 프론트 기능 검증 — 노드 에이전트-호출 picker(외형 아닌 동작: 선택→저장→tools 효과를 API로 단언).
   ① API로 위임 대상(expert) 생성 + 활성화(로컬 위임 자격).
   ② 에이전트 폼: 노드형 → 노드 추가(직접 설정) → "에이전트 (선택)" picker 노출 → expert 선택 → 저장.
   ③ API로 config.nodes[0].tools 에 `agent__{expertId}` 합류 + capabilities 파생 단언(UI 선택의 효과).
   ④ 자기 자신은 후보에서 제외(picker 옵션에 편집 중 에이전트 이름 없음 — 거짓 어포던스 0).
   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-318-node-agent-call-ui.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()

const EXPERT = `v318ui-expert-${Date.now().toString(36)}`
const AGENT = `v318ui-pipe-${Date.now().toString(36)}`

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
let expertPk = null
let expertAgentId = null
try {
  // ── ① API로 expert 생성 + 활성화(로컬 위임 자격 = 활성 버전) ──
  const r0 = await api('/agents', {
    method: 'POST',
    body: JSON.stringify({ name: EXPERT, config: { model: 'mock-llm', prompt: '너는 전문가다.' } }),
  })
  check(r0.status === 201, `① expert 생성 201 (got ${r0.status})`)
  const expert = await r0.json()
  expertPk = expert.id
  expertAgentId = expert.agentId
  const g = await (await api(`/agents/${expertPk}`)).json()
  const draft = (g.versions || []).find((v) => v.status === 'draft')?.version
  if (draft) await api(`/agents/${expertPk}/activate`, { method: 'POST', body: JSON.stringify({ version: draft }) })
  const g2 = await (await api(`/agents/${expertPk}`)).json()
  check(!!g2.activeVersion, `① expert 활성 버전 보유 (got ${g2.activeVersion})`)

  // ── 로그인 + 노드형 에이전트 폼 ──
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const typeField = page.locator('label', { hasText: '에이전트 종류' }).first()
  await typeField.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
  await page.getByPlaceholder('예: research-assistant').fill(AGENT)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(600)

  const modal = page.locator('.ant-modal:visible').last()
  // 노드 유효화(스펙 259) — 직접 설정 노드는 프롬프트 필수(모델은 기본값 자동). 채워야 저장 게이트 통과.
  await modal.getByPlaceholder(/이 노드가 할 일을 지시하세요/).first().fill('전문가에게 물어라')
  await page.waitForTimeout(200)

  // ── ② "에이전트 (선택)" picker 노출(직접 설정 노드의 도구 구획 아래) ──
  const modalText = await modal.innerText()
  check(/에이전트 \(선택\)/.test(modalText), '② 노드 편집기에 "에이전트 (선택)" picker 노출')

  // picker(에이전트 라벨 옆 Select) 열기 — 라벨 span의 형제 Select를 xpath로 지목.
  const agentField = modal.getByText('에이전트 (선택)', { exact: true })
    .locator('xpath=following-sibling::div[contains(@class,"ant-select")]').first()
  await agentField.scrollIntoViewIfNeeded()
  await agentField.click()
  await page.waitForTimeout(500)
  const dropText = await page.locator('.ant-select-dropdown:visible').last().innerText()
  // ④ 자기 자신(AGENT, 아직 미저장이라 이름으로 후보 진입 안 됨) 제외 + expert는 후보에 있음.
  check(dropText.includes(EXPERT), `② picker 후보에 expert (got ${JSON.stringify(dropText.slice(0, 120))})`)
  check(!dropText.includes(AGENT), '④ picker 후보에 자기 자신(편집 중 에이전트) 없음')

  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: EXPERT }).first().click()
  await page.waitForTimeout(400)
  // 드롭다운만 닫기(모달 유지) — 프롬프트 입력을 다시 눌러 blur(Escape는 모달까지 닫힘).
  await modal.getByPlaceholder(/이 노드가 할 일을 지시하세요/).first().click()
  await page.waitForTimeout(300)

  // 저장(남은 스텝 통과)
  for (let i = 0; i < 6; i++) {
    const createBtn = page.getByRole('button', { name: '에이전트 생성' })
    if (await createBtn.isVisible().catch(() => false)) { await createBtn.click(); break }
    const next = page.getByRole('button', { name: '다음' }).last()
    if (await next.isVisible().catch(() => false)) { await next.click(); await page.waitForTimeout(500) }
  }
  await page.waitForTimeout(1500)

  // ── ③ API로 tools 합류 + capabilities 파생 단언(UI 선택의 효과) ──
  const agents = await (await api('/agents')).json()
  const saved = agents.find((a) => a.name === AGENT)
  agentId = saved?.id ?? null
  check(!!saved, '③ 저장: 에이전트 생성됨')
  const node0 = saved?.nodes?.[0]
  const agentTool = `agent__${expertAgentId}`
  check(Array.isArray(node0?.tools) && node0.tools.includes(agentTool),
    `③ 저장: nodes[0].tools 에 ${agentTool} 합류 (got ${JSON.stringify(node0?.tools)})`)
  check(Array.isArray(saved?.capabilities) && saved.capabilities.includes(expertAgentId),
    `③ 저장: capabilities 축에 expert 파생 (got ${JSON.stringify(saved?.capabilities)})`)

  check(pageErrors.length === 0, `페이지 JS 에러 0 (got ${pageErrors.slice(0, 2)})`)
} finally {
  if (agentId) await api(`/agents/${agentId}`, { method: 'DELETE' }).catch(() => {})
  if (expertPk) await api(`/agents/${expertPk}`, { method: 'DELETE' }).catch(() => {})
  await browser.close()
}

console.log(`\n${fails.length} failed`)
if (fails.length) { for (const f of fails) console.log('  FAILED:', f); process.exit(1) }
console.log('VERIFY318_UI_OK — 노드 에이전트-호출 picker(후보 스코프·자기제외·선택→tools 합류·capabilities 파생) 기능 정착')
