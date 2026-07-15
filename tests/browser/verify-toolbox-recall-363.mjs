/* 스펙 363 — 도구 무발동 박스는 메모리 회상 턴에 억제, 맨 턴엔 그대로.
   단순 에이전트(메모리+calc-tools MCP 바인딩)로 두 턴을 실측:
   A(회상 턴): 시드 기억과 동일 텍스트 질문 → 회상≥1·도구0 → 실행흐름에 "호출되지 않았습니다" Alert 없음.
   B(맨 턴):   시드 무매치·도구 키워드 없는 유니크 질문 → 회상0·도구0 → 그 Alert 그대로 표시(스펙 236 보존).

   전제: 서버 8000(새 Inspector)·admin 5173, admin 유저 스코프에 RECALL_MSG와 동일 텍스트 기억 시드
        (tests/browser/_seed_user_mem_363.py seed admin@example.com "<RECALL_MSG>").
   실행: PLAYWRIGHT_DIR=<dir> RECALL_MSG="..." ADMIN_EMAIL=... ADMIN_PASSWORD=... OUTDIR=<dir> \
        node tests/browser/verify-toolbox-recall-363.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const OUTDIR = process.env.OUTDIR ?? '/tmp'
const MODEL = process.env.CHAT_MODEL ?? 'mock-llm'
const RECALL_MSG = process.env.RECALL_MSG ?? '363 지난번에 도시락 역사를 물어봤어'
const stamp = Date.now().toString(36)
const BARE_MSG = `363 맨턴 유니크 질문 ${stamp} 어떻게 지내` // 시드 무매치·도구 키워드 없음
const NOFIRE = '호출되지 않았습니다' // 도구 무발동 Alert 제목 일부

const simpleMemMcp = () => ({
  model: MODEL, persona: '', memories: ['장기 기억 (mem0)'], mcps: ['calc-tools'], vectorTables: [],
})

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1500, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

let lastTrace = null
page.on('response', async (resp) => {
  try {
    if (resp.request().method() !== 'POST' || !/\/agents\/.+\/chat$/.test(resp.url())) return
    const text = await resp.text()
    for (const f of text.split('\n\n')) {
      const ev = f.split('\n').find((l) => l.startsWith('event: '))?.slice(7)
      const dl = f.split('\n').find((l) => l.startsWith('data: '))
      if (ev === 'trace' && dl) { try { lastTrace = JSON.parse(dl.slice(6)) } catch {} }
    }
  } catch { /* 스트림 경합 무시 */ }
})

async function selectAgent(name) {
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(name, { exact: false }).first().click()
  await page.waitForTimeout(500)
}

async function createAgent(name, config) {
  return page.evaluate(async ({ nm, cfg }) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text(); let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config: cfg }) })
    if (!cr.ok) return { ok: false, step: 'create', body: cr.t.slice(0, 200) }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    if (!ac.ok) return { ok: false, step: 'activate', status: ac.status }
    return { ok: true, id: cr.j.id }
  }, { nm: name, cfg: config })
}

// 한 에이전트에 한 메시지 보내고 (trace, 실행흐름 페이지텍스트) 회수.
async function runTurn(name, msg) {
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(700)
  await selectAgent(name)
  lastTrace = null
  const box = page.locator('textarea').first()
  await box.click(); await box.fill(msg); await page.waitForTimeout(150); await box.press('Enter')
  const chip = page.getByText(/\d+\s*mem/).last()
  const arrived = await chip.waitFor({ state: 'visible', timeout: 90000 }).then(() => true).catch(() => false)
  if (!arrived) return { arrived: false }
  await chip.click({ timeout: 8000 })
  await page.waitForTimeout(500)
  const flowTab = page.getByRole('tab', { name: /실행 흐름/ }).first()
  if (await flowTab.isVisible().catch(() => false)) { await flowTab.click(); await page.waitForTimeout(300) }
  const bodyText = await page.locator('#root').innerText().catch(() => '')
  return { arrived: true, trace: lastTrace, bodyText }
}

const createdIds = []
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  const nameA = `tb363-recall-${stamp}`
  const nameB = `tb363-bare-${stamp}`
  for (const [nm] of [[nameA], [nameB]]) {
    const s = await createAgent(nm, simpleMemMcp())
    if (!s.ok) { check(false, `에이전트 생성 ${nm} (${s.step} ${s.body ?? s.status ?? ''})`); throw new Error('셋업 실패') }
    createdIds.push(s.id)
  }

  // ── A: 회상 턴 — 박스 억제 ────────────────────────────────────────────────
  const a = await runTurn(nameA, RECALL_MSG)
  check(a.arrived, 'A(회상) 응답 도착')
  if (a.arrived) {
    const recalled = (a.trace?.memories?.length ?? 0) > 0
    check(recalled, `A: 회상 실제 발생 (memories=${a.trace?.memories?.length ?? 0})`)
    check((a.trace?.toolDiag?.called ?? 0) === 0, 'A: MCP 도구 미호출 (called=0 — 박스 조건 성립 상황)')
    check(!a.bodyText.includes(NOFIRE), 'A: 실행흐름에 "호출되지 않았습니다" Alert 없음 (스펙 363 억제)')
    await page.screenshot({ path: `${OUTDIR}/tb363-recall.png`, fullPage: false })
    log(`  shot: ${OUTDIR}/tb363-recall.png`)
  }

  // ── B: 맨 턴 — 박스 그대로 ────────────────────────────────────────────────
  const b = await runTurn(nameB, BARE_MSG)
  check(b.arrived, 'B(맨턴) 응답 도착')
  if (b.arrived) {
    check((b.trace?.memories?.length ?? 0) === 0, `B: 회상 없음 (memories=${b.trace?.memories?.length ?? 0})`)
    check((b.trace?.toolDiag?.called ?? 0) === 0, 'B: MCP 도구 미호출 (called=0)')
    check(b.bodyText.includes(NOFIRE), 'B: 맨 턴엔 "호출되지 않았습니다" Alert 그대로 표시 (스펙 236 보존)')
    await page.screenshot({ path: `${OUTDIR}/tb363-bare.png`, fullPage: false })
    log(`  shot: ${OUTDIR}/tb363-bare.png`)
  }
} catch (e) {
  log('ERR ' + (e?.stack ?? e))
  await page.screenshot({ path: `${OUTDIR}/tb363-error.png`, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  for (const id of createdIds) {
    await page.evaluate(async (i) => { await fetch(`/api/agents/${i}`, { method: 'DELETE', credentials: 'include' }).catch(() => {}) }, id)
  }
  await browser.close()
}
log('\n' + (fails.length ? `FAIL ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN (verify-toolbox-recall-363)'))
process.exit(fails.length ? 1 : 0)
