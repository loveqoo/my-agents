/* 에이전트 상세 화면 정비 검증 (스펙 286) — 필수 단언(UI 기능적).
   ① 개요 구성 행 카운트=tools 기준(도구 2 — 서버 수 1 아님) + 구성 탭 도구 태그(서버 · 도구).
   ② 노드형: 헤더 종류 '노드형'(내부 키 pipeline 미노출) + 개요 '노드 2' + 구성 탭 노드 행.
   ③ 헤더 배지 슬림화: private/public·초안·A2A·서빙 태그 부재 + 신호등 점(aria-label) 존재.
   ④ 어휘: '메모리'→'기억'·'벡터 테이블'→'문서'·'지표 없음'→'피드백 아직 없음'.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-286-agent-detail.mjs */
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
const D = 'dt286-direct-' + rand, P = 'dt286-pipe-' + rand
const cleanup = { agents: [] }

const openDetail = async (name) => {
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(500)
  await page.getByPlaceholder('이름 검색').fill(name)
  await page.waitForTimeout(500)
  await page.locator('.dt-antd tbody tr', { has: page.getByText(name, { exact: false }) }).first().click()
  await page.waitForTimeout(600)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 픽스처: 직접형(도구 2개=서버 1개 — 카운트 구분자) + 노드형(노드 2개)
  const made = await page.evaluate(async ({ D, P }) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (body) => { const r = await fetch('/api/agents', { method: 'POST', credentials: 'include', headers: H, body: JSON.stringify(body) }); return r.ok ? (await r.json()).id : null }
    return {
      d: await jf({ name: D, config: { model: 'mock-llm', persona: 't', mcps: ['local-tools'], tools: ['local-tools__echo', 'local-tools__web_search'], memories: ['장기 기억 (mem0)'] } }),
      p: await jf({ name: P, config: { model: 'mock-llm', persona: '', impl: 'pipeline', nodes: [{ name: 'n1', prompt: 'p', model: 'mock-llm', tools: [] }, { name: 'n2', prompt: 'p', model: 'mock-llm', tools: [] }] } }),
    }
  }, { D, P })
  for (const id of Object.values(made)) if (id) cleanup.agents.push(id)
  check(made.d && made.p, `픽스처 생성 (${JSON.stringify(made)})`)
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(800)

  // ── 직접형 상세 ──
  await openDetail(D)
  const overview = await page.locator('.ant-descriptions').first().innerText()
  check(overview.includes('도구 2'), `① 개요 구성 행 '도구 2'(tools 기준) (got ${JSON.stringify(overview.match(/도구 ?\S*/)?.[0] ?? '')})`)
  check(!overview.includes('도구 1'), `① '도구 1'(서버 수) 미노출`)
  check(overview.includes('기억 1') && !overview.includes('메모리'), `④ 개요 '기억 1'(메모리 아님)`)
  check(overview.includes('피드백 아직 없음') && !overview.includes('지표 없음'), `④ 운영 행 '피드백 아직 없음'`)
  // 헤더 배지 슬림화 — 신호등 점 + 종류만, 구 태그 부재
  check((await page.locator('span[aria-label="유휴"]').count()) > 0, `③ 신호등 점(유휴) 존재`)
  check((await page.locator('.ant-tag', { hasText: '직접 응답' }).count()) > 0, `③ 종류 태그 '직접 응답'`)
  for (const t of ['private', 'public', 'A2A', '미서빙 · 초안만']) {
    check((await page.locator('.ant-tag', { hasText: t }).count()) === 0, `③ 구 태그 '${t}' 부재`)
  }
  check((await page.locator('.ant-tag').filter({ hasText: /^초안/ }).count()) === 0, `③ 헤더 초안 태그 부재(개요 행이 소유)`)
  // 구성 탭 — 도구 태그(서버 · 도구), 어휘
  await page.getByRole('tab', { name: '구성' }).click()
  await page.waitForTimeout(500)
  const cfgTxt = await page.locator('.ant-descriptions').first().innerText()
  check(cfgTxt.includes('local-tools · echo') && cfgTxt.includes('local-tools · web_search'), `① 구성 탭 도구 태그 2(서버 · 도구)`)
  check(!cfgTxt.includes('벡터 테이블') && !cfgTxt.includes('MCP'), `④ 구성 탭 '벡터 테이블'/'MCP' 라벨 부재`)

  // ── 노드형 상세 ──
  await page.getByRole('button', { name: /에이전트 목록/ }).click()
  await page.waitForTimeout(500)
  await openDetail(P)
  check((await page.locator('.ant-tag', { hasText: '노드형' }).count()) > 0, `② 헤더 종류 '노드형'`)
  check((await page.locator('.ant-tag').filter({ hasText: /^pipeline$/ }).count()) === 0, `② 내부 키 'pipeline' 미노출`)
  const ov2 = await page.locator('.ant-descriptions').first().innerText()
  check(ov2.includes('노드 2'), `② 개요 구성 행 '노드 2' (got ${JSON.stringify(ov2.match(/노드 ?\S*/)?.[0] ?? '')})`)
  await page.getByRole('tab', { name: '구성' }).click()
  await page.waitForTimeout(500)
  const cfg2 = await page.locator('.ant-descriptions').first().innerText()
  check(cfg2.includes('n1') && cfg2.includes('n2') && cfg2.includes('mock-llm'), `② 구성 탭 노드 행(이름·모델)`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
