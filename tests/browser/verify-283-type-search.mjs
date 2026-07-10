/* 에이전트 종류 검색 검증 (스펙 283) — 필수 단언(UI 기능적).
   ① '노드형' 검색 → 노드형만(직접형 미노출). ② '조율형' 검색 → 조율형만.
   ③ 이름 검색 무회귀. 실행: PLAYWRIGHT_DIR=... node tests/browser/verify-283-type-search.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1100 } })).newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const rand = Date.now().toString(36)
const D = 'ts283-direct-' + rand, P = 'ts283-pipe-' + rand, O = 'ts283-orch-' + rand
const cleanup = { agents: [] }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 픽스처 3종(직접/노드형/조율형)
  const made = await page.evaluate(async ({ D, P, O }) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, body) => { const r = await fetch(url, { method: 'POST', credentials: 'include', headers: H, body: JSON.stringify(body) }); return r.ok ? (await r.json()).id : null }
    return {
      d: await jf('/api/agents', { name: D, config: { model: 'mock-llm', persona: 't' } }),
      p: await jf('/api/agents', { name: P, config: { model: 'mock-llm', persona: '', impl: 'pipeline', nodes: [{ name: 'n', prompt: 'p', model: 'mock-llm', tools: [] }] } }),
      o: await jf('/api/agents', { name: O, config: { model: 'mock-llm', persona: 't', impl: 'orchestrate', capabilities: [] } }),
    }
  }, { D, P, O })
  for (const id of Object.values(made)) if (id) cleanup.agents.push(id)
  check(made.d && made.p && made.o, `픽스처 생성 (${JSON.stringify(made)})`)
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(800)

  const search = page.getByPlaceholder('이름·종류·모델 검색').first()
  check(await search.count() > 0, `placeholder '이름·종류·모델 검색'`)

  const visible = async (name) => (await page.getByText(name, { exact: false }).count()) > 0

  // ① 노드형
  await search.fill('노드형'); await page.waitForTimeout(500)
  check(await visible(P), `① '노드형' 검색 → 노드형 노출`)
  check(!(await visible(D)), `① '노드형' 검색 → 직접형 미노출`)
  // ② 조율형
  await search.fill('조율형'); await page.waitForTimeout(500)
  check(await visible(O), `② '조율형' 검색 → 조율형 노출`)
  check(!(await visible(P)), `② '조율형' 검색 → 노드형 미노출`)
  // ③ 이름 무회귀
  await search.fill(D); await page.waitForTimeout(500)
  check(await visible(D), `③ 이름 검색 무회귀`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
