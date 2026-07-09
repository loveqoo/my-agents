/* 노드형 RAG 인스펙터 표면 검증 (스펙 266) — `<노드>__tools` 귀속 수정 확인.
   노드형 RAG 에이전트 생성·활성 → 플레이그라운드 UI 대화 → 인스펙터 열기 →
   도구 노드 행에 RagCall 카드(search_documents·N건·검색어·히트)가 표면되는지 필수 단언 + 스크린샷.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-pipeline-rag-inspector.mjs tests/browser/out-raginsp */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/rag-insp'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const NAME = 'rag-insp-' + Date.now().toString(36)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  const setup = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      return { ok: r.ok, status: r.status, j: await r.json().catch(() => null) }
    }
    const config = {
      model: 'qwen3.6-35b', persona: '', impl: 'pipeline',
      historyDepth: 20, persistHistory: true, ephemeral: false,
      memories: [], mcps: [], vectorTables: ['docs-kb'],
      nodes: [{
        name: '문서답변', context: 'carry', model: 'qwen3.6-35b', tools: ['search_documents'],
        prompt: '반드시 먼저 search_documents 도구로 지식베이스를 검색하고, 검색된 문서 내용에 근거해서만 답하세요. 근거 문서의 표현을 인용하세요.',
      }],
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    return ac.ok ? { step: 'ok', id: cr.j.id } : { step: 'activate', status: ac.status }
  }, NAME)
  check(setup.step === 'ok', `노드형 RAG 에이전트 준비 (step=${setup.step})`)
  if (setup.step !== 'ok') throw new Error('셋업 실패')

  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(NAME, { exact: false }).first().click()
  await page.waitForTimeout(600)

  const box = page.locator('textarea').first()
  await box.click()
  await box.fill('지식베이스에서 계정 생성 방법을 검색해 문서 내용대로 알려줘.')
  await page.waitForTimeout(200)
  await box.press('Enter')
  const chip = page.getByText(/\d+\s*rag/).last()
  const arrived = await chip.waitFor({ state: 'visible', timeout: 120000 }).then(() => true).catch(() => false)
  check(arrived, '응답 도착(rag 칩 표시)')
  const chipText = arrived ? await chip.innerText().catch(() => '') : ''
  check(/[1-9]\d*\s*rag/.test(chipText), `rag 칩 ≥1 (got "${chipText}")`)
  if (arrived) await chip.click({ timeout: 8000 })
  await page.waitForTimeout(700)

  const body = await page.locator('#root').innerText().catch(() => '')
  // 핵심(스펙 266): 도구 노드(문서답변__tools) 행 + RagCall 카드 내용 표면
  check(/도구·문서 검색 실행 · 문서답변/.test(body), '도구 노드 라벨(도구·문서 검색 실행 · 문서답변)')
  check(/search_documents/.test(body), 'RagCall: search_documents 표시')
  check(/[1-9]\d*건/.test(body), 'RagCall: 검색 N건(≥1) 표시')
  check(/검색어/.test(body), 'RagCall: 검색어 에코 표시')
  check(!/sk-[A-Za-z0-9_-]{6,}/.test(body), '비밀 미표면')
  await page.screenshot({ path: `${OUT}-inspector.png`, fullPage: false })
  log('shot: ' + OUT + '-inspector.png')

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
