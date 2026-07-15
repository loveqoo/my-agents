/* 스펙 362 P2 — 에이전트유형 × 능력 × 인스펙터 매트릭스(전수조사 편입).
   각 셀에서 (a) 능력이 실제 실행되나(SSE trace 실측), (b) 인스펙터가 내용까지 표시하나(실행흐름
   페이지텍스트에 회상 본문 등) 이중 단언. 반복된 회상 표시 버그(359 노드형·362 단순형)의 근본인
   "유형마다 다른 메커니즘 → 표시 유형별 배선 누락"을 상시 회귀로 잡는다.

   현재 셀: memory 행(단순·노드형). rag·mcp 행, 조율형은 후속 확장(미확인 셀은 SKIP 로그로 명시).

   전제: 서버 8000·admin 5173(새 코드), admin 스코프에 회상 쿼리(=MSG)와 동일 텍스트 기억 시드.
   실행: PLAYWRIGHT_DIR=<dir> ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         OUTDIR=<dir> node tests/browser/verify-inspector-matrix.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const OUTDIR = process.env.OUTDIR ?? '/tmp'
const MODEL = process.env.CHAT_MODEL ?? 'mock-llm'
const MSG = '내가 과거에 무엇을 검색했는지 알려줘 matrix362' // = 시드한 admin 기억 텍스트(정확 일치 회상)
const stamp = Date.now().toString(36)

// 능력별 config 팩토리 — 유형(단순/노드형) × 능력(memory) 셀.
const memConfigSimple = () => ({
  model: MODEL, persona: '', memories: ['장기 기억 (mem0)'], mcps: [], vectorTables: [],
})
const memConfigPipeline = () => ({
  model: MODEL, persona: '', impl: 'pipeline', memories: ['장기 기억 (mem0)'], mcps: [], vectorTables: [],
  nodes: [
    { name: '확인', context: 'carry', model: MODEL, tools: [], memories: ['장기 기억 (mem0)'], memoryQuery: 'user', prompt: '위 내용을 한 문장으로 요약하세요.' },
  ],
})

const CELLS = [
  { type: '단순(ui)', cap: 'memory', spec: 362, name: `mtx-simple-mem-${stamp}`, config: memConfigSimple,
    // 실행: trace.memories(회상 히트)에 내용 / 표시: 실행흐름에 "메모리 회상" + 회상 본문
    execOk: (tr) => (tr?.memories?.length ?? 0) > 0,
    displayLabel: /메모리 회상/ },
  { type: '노드형(pipeline)', cap: 'memory', spec: 359, name: `mtx-pipe-mem-${stamp}`, config: memConfigPipeline,
    execOk: (tr) => (tr?.memoryRecalls?.length ?? 0) > 0 && (tr.memoryRecalls[0]?.memories?.length ?? 0) > 0,
    displayLabel: /기억 회상/ },
]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1500, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

// chat SSE 응답에서 trace 이벤트를 뽑는다(네트워크 바디 파싱).
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

const createdIds = []
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(800)

  for (const cell of CELLS) {
    const tag = `[${cell.type} × ${cell.cap}]`
    const setup = await createAgent(cell.name, cell.config())
    if (!setup.ok) { check(false, `${tag} 에이전트 생성 (${setup.step} ${setup.body ?? setup.status ?? ''})`); continue }
    createdIds.push(setup.id)
    // 새 에이전트를 스위처 목록에 반영 — reload는 domcontentloaded로(이전 SSE 스트림이 networkidle 방해).
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 })
    await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
    await page.getByRole('menuitem', { name: 'Playground' }).click()
    await page.waitForTimeout(700)
    await selectAgent(cell.name)

    lastTrace = null
    const box = page.locator('textarea').first()
    await box.click(); await box.fill(MSG); await page.waitForTimeout(150); await box.press('Enter')

    const chip = page.getByText(/\d+\s*mem/).last()
    const arrived = await chip.waitFor({ state: 'visible', timeout: 90000 }).then(() => true).catch(() => false)
    check(arrived, `${tag} 응답 도착`)
    if (!arrived) continue
    await chip.click({ timeout: 8000 })
    await page.waitForTimeout(500)
    const flowTab = page.getByRole('tab', { name: /실행 흐름/ }).first()
    if (await flowTab.isVisible().catch(() => false)) { await flowTab.click(); await page.waitForTimeout(300) }

    const bodyText = await page.locator('#root').innerText().catch(() => '')
    // (a) 실행 — SSE trace가 능력 내용을 실었나
    check(cell.execOk(lastTrace), `${tag} 실행: 회상 내용이 trace에 실림 (spec ${cell.spec})`)
    // (b) 표시 — 인스펙터 실행흐름에 회상 라벨 + 회상 본문(=MSG) 표시(카운트만 아님)
    check(cell.displayLabel.test(bodyText), `${tag} 표시: 실행흐름에 회상 라벨`)
    check(bodyText.includes(MSG), `${tag} 표시: 회상 본문(내용)이 실행흐름에 보임 — 카운트만 아님`)
    await page.screenshot({ path: `${OUTDIR}/matrix-${cell.name}.png`, fullPage: false })
    log(`  shot: ${OUTDIR}/matrix-${cell.name}.png`)
  }

  // 미확인 셀 명시(은폐 금지, 스펙 362 P2-C3)
  log('  SKIP  [rag 행 · mcp 행 · 조율형 유형] — 후속 확장(미확인 셀, 매트릭스 골격만 착지)')
} catch (e) {
  log('ERR ' + (e?.stack ?? e))
  await page.screenshot({ path: `${OUTDIR}/matrix-error.png`, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  // 정리 — 생성 에이전트 삭제
  for (const id of createdIds) {
    await page.evaluate(async (i) => { await fetch(`/api/agents/${i}`, { method: 'DELETE', credentials: 'include' }).catch(() => {}) }, id)
  }
  await browser.close()
}
log('\n' + (fails.length ? `FAIL ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN (verify-inspector-matrix)'))
process.exit(fails.length ? 1 : 0)
