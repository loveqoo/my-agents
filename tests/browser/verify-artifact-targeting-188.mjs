/* 스펙 188 P2~P4 — targeting 데모 플레이그라운드 e2e.
   A) 전체 조건 발화 → 동적 폼(4필드·후보·프리필) 렌더 → 제출 → artifact 카드(conditions JSON).
   B) 일부 조건 발화 → 폼(구매이력 미충족) → **채팅 텍스트**로 보완(이중 입력) → artifact.
   served MCP targeting-catalog(시드 reconcile) + artifact_targeting impl 사용. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
const NAME = `targeting-${Date.now().toString(36)}`

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]

// targeting-catalog 서빙 게이트(스펙 156: published=True일 때만 서빙) — 데모 카탈로그(read-only)를
// 켠다. 정리 시 원상복구.
const blocks = await (await fetch(`${API}/blocks`, { headers: { Cookie: cookie } })).json()
const catalogRow = (blocks.mcp?.items || []).find((m) => m.name === 'targeting-catalog')
if (!catalogRow) { console.log('FAIL targeting-catalog 행 없음(시드 reconcile 미실행?)'); process.exit(1) }
const wasPublished = !!catalogRow.published
if (!wasPublished) {
  await fetch(`${API}/mcp-servers/${catalogRow.id}/publish`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: JSON.stringify({ published: true }),
  })
  console.log('CATALOG_PUBLISHED')
}

const created = await (await fetch(`${API}/agents`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Cookie: cookie },
  body: JSON.stringify({
    name: NAME, alias: null,
    config: {
      model: 'mock-llm', prompt: 'methodical-researcher', temperature: null,
      memories: [], historyDepth: 10, persistHistory: true,
      vectorTables: [], mcps: [], impl: 'artifact_targeting',
      capabilities: ['mcp:targeting-catalog'], toolPolicy: {},
    },
  }),
})).json()
if (!created.id) { console.log('FAIL 에이전트 생성:', JSON.stringify(created).slice(0, 200)); process.exit(1) }
console.log('AGENT_CREATED', NAME)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

const waitFor = async (pattern, timeout = 25000) => {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    const body = await page.locator('#root').innerText()
    if (pattern.test(body)) return true
    await page.waitForTimeout(700)
  }
  return false
}
const say = async (text) => {
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill(text); await ta.press('Enter')
}
const resetConvo = async () => {
  const btn = page.getByRole('button', { name: /대화 초기화|새 대화/ }).first()
  if (await btn.count()) { await btn.click().catch(() => {}); await page.waitForTimeout(600) }
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  const combo = page.locator('button').filter({ hasText: /research-assistant|에이전트/ }).first()
  await combo.click(); await page.waitForTimeout(400)
  await page.getByText(NAME, { exact: false }).first().click()
  await page.waitForTimeout(500)

  // ── A) 전체 조건 → 동적 폼(프리필 완비, confirm) → 제출 → artifact 카드 ──
  await say('최근 구매 이력이 있는 30대 서울에 거주하는 남성')
  ok(await waitFor(/입력이 필요합니다 — 폼으로 고르거나/), 'A1 폼 패널 렌더')
  const body1 = await page.locator('#root').innerText()
  ok(/구매이력/.test(body1) && /나이/.test(body1) && /거주지/.test(body1) && /성별/.test(body1),
    'A2 동적 합성 4필드(구매이력·나이·거주지·성별)')
  await page.screenshot({ path: `${OUT}/targeting-188-form.png` })
  // 프리필 확인(셀렉트 표시값) — 최근·30대·서울·남성이 이미 선택돼 있어야
  ok(/최근/.test(body1) && /30대/.test(body1) && /서울/.test(body1) && /남성/.test(body1),
    'A3 발화 프리필(최근·30대·서울·남성)')
  await page.getByRole('button', { name: '제출', exact: true }).click()
  ok(await waitFor(/산출물 완성.*targeting|산출물/), 'A4 제출 → artifact')
  ok(await waitFor(/purchase_history/), 'A5 artifact 카드에 conditions JSON')
  await page.screenshot({ path: `${OUT}/targeting-188-artifact.png` })

  // ── B) 일부 조건 → 폼(구매이력 빈 값) → 채팅 텍스트로 보완(이중 입력) → artifact ──
  await resetConvo()
  await say('구매 이력이 있는 30대 서울 거주 남성')
  ok(await waitFor(/입력이 필요합니다 — 폼으로 고르거나/), 'B1 폼 재렌더(구매이력 미충족)')
  // 제출 버튼이 비활성(필수 미충족)이어야 — 이중 입력 유도 상태
  const submitDisabled = await page.getByRole('button', { name: '제출', exact: true }).isDisabled().catch(() => false)
  ok(submitDisabled, 'B2 필수 미충족 시 제출 비활성')
  await page.screenshot({ path: `${OUT}/targeting-188-dualinput-before.png` })
  await say('구매 이력은 최근 한 달로 해줘')
  // confirm=True 계약: 텍스트 병합은 폼을 곧장 확정하지 않고 **갱신 프리필로 재제시**한다(무확인
  // 확정 봉인 — 적대 검증 P2-2). "확인 후 제출" 노트가 뜨고, 병합값(최근 한 달)이 프리필돼야.
  ok(await waitFor(/최근 한 달/), 'B3 텍스트 병합 반영(최근 한 달)')
  ok(await waitFor(/확인 후 제출|입력이 필요합니다 — 폼으로 고르거나/), 'B3b 병합 후 폼 재제시(무확인 확정 안 함)')
  // 이제 필수 충족 → 제출 활성 → 사용자가 명시 제출로 확정.
  const submitNowEnabled = !(await page.getByRole('button', { name: '제출', exact: true }).isDisabled().catch(() => true))
  ok(submitNowEnabled, 'B3c 병합 후 제출 활성(필수 충족)')
  await page.getByRole('button', { name: '제출', exact: true }).click()
  ok(await waitFor(/purchase_history|산출물/), 'B4 이중 입력(텍스트 보완+폼 확정)으로 artifact 완성')
  await page.screenshot({ path: `${OUT}/targeting-188-dualinput-done.png` })

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  await fetch(`${API}/agents/${created.id}`, { method: 'DELETE', headers: { Cookie: cookie } }).catch(() => {})
  if (!wasPublished) {
    await fetch(`${API}/mcp-servers/${catalogRow.id}/publish`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Cookie: cookie },
      body: JSON.stringify({ published: false }),
    }).catch(() => {})
  }
  console.log('AGENT_DELETED', NAME)
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (TARGETING188_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
