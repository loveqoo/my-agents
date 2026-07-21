/* 스펙 188 P1 — 산출물형(artifact_slotfill) 플레이그라운드 e2e.
   "출장 신청할게" → 목적지/기간/예산 3회 ask 왕복(멀티턴 interrupt·Command 재개) →
   최종 "산출물 완성 — travel-request" 요약 + 값 반영 확인. 기존 에이전트 무회귀는 별도 스위트. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = _fx.email
const PASSWORD = _fx.password
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-{{GITHUB_ORG}}-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'
const NAME = `slotfill-${Date.now().toString(36)}`

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

// ── API로 데모 에이전트 생성(정리까지 이 스크립트가 책임) ──
const login = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(EMAIL)}&password=${encodeURIComponent(PASSWORD)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]
if (!cookie) { console.log('FAIL 로그인 쿠키 없음'); process.exit(1) }
const created = await (await fetch(`${API}/agents`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Cookie: cookie },
  body: JSON.stringify({
    name: NAME,
    alias: null,
    config: {
      model: 'mock-llm', prompt: 'methodical-researcher', temperature: null,
      memories: [], historyDepth: 10, persistHistory: true,
      vectorTables: [], mcps: [], impl: 'artifact_slotfill', capabilities: [], toolPolicy: {},
    },
  }),
})).json()
if (!created.id) { console.log('FAIL 에이전트 생성 실패:', JSON.stringify(created).slice(0, 200)); process.exit(1) }
console.log('AGENT_CREATED', NAME)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

// 마지막 봇 발화가 pattern을 담을 때까지 대기(스트림 done까지 폴링)
const waitBot = async (pattern, timeout = 25000) => {
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

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // Playground에서 데모 에이전트 선택
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  const combo = page.locator('button').filter({ hasText: /research-assistant|에이전트/ }).first()
  await combo.click(); await page.waitForTimeout(400)
  await page.getByText(NAME, { exact: false }).first().click()
  await page.waitForTimeout(500)

  // ── ask 왕복 3회 ──
  await say('출장 신청할게')
  ok(await waitBot(/목적지.*알려주세요/), 'Q1 목적지 질문')
  await say('서울')
  ok(await waitBot(/기간.*알려주세요/), 'Q2 기간 질문(재개 후 다음 ask)')
  await say('3월 2일부터 3일')
  ok(await waitBot(/예산.*알려주세요/), 'Q3 예산 질문')
  await page.screenshot({ path: `${OUT}/artifact-188-asking.png` })
  await say('50만원')
  ok(await waitBot(/산출물 완성.*travel-request/), 'A1 산출물 완성 요약')
  const body = await page.locator('#root').innerText()
  ok(/destination=서울/.test(body), 'A2 목적지 값 반영')
  ok(/budget=50만원/.test(body), 'A3 예산 값 반영')
  await page.screenshot({ path: `${OUT}/artifact-188-done.png` })

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  // 정리 — 데모 에이전트 삭제
  await fetch(`${API}/agents/${created.id}`, { method: 'DELETE', headers: { Cookie: cookie } }).catch(() => {})
  console.log('AGENT_DELETED', NAME)
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (ARTIFACT188_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
