/* 노드형 인스펙터 표면 확인 (스펙 259-261) — 시스템 Chrome.
   노드형 에이전트를 만들어 활성화 → 플레이그라운드 UI에서 대화 → 트레이스 칩 클릭해 인스펙터 열기 →
   "LangGraph 경로"에 노드(분석·요약)가 순서대로·읽기 좋게 보이는지 스크린샷+텍스트로 확인.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-pipeline-inspector.mjs tests/browser/out-insp */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/pipeline-insp'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const NAME = 'node-insp-' + Date.now().toString(36)

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

  // 노드형 에이전트 생성 + 활성화 (브라우저 세션 fetch)
  const setup = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const config = {
      model: 'mock-llm', persona: '', impl: 'pipeline',
      historyDepth: 20, persistHistory: true, ephemeral: false,
      nodes: [
        { name: '분석', prompt: '입력을 분석하라', model: 'mock-llm', tools: [], context: 'carry' },
        { name: '요약', prompt: '요약하라', model: 'mock-llm', tools: [], context: 'clean', format: 'json', fields: ['summary'] },
      ],
    }
    const cr = await (await fetch('/api/agents', { method: 'POST', credentials: 'include', headers: H, body: JSON.stringify({ name: nm, description: null, config }) })).json()
    const draft = (cr.versions || []).find((v) => v.status === 'draft') || (cr.versions || [])[0]
    await fetch(`/api/agents/${cr.id}/activate`, { method: 'POST', credentials: 'include', headers: H, body: JSON.stringify({ version: draft?.version }) })
    return { id: cr.id, name: cr.name }
  }, NAME)
  log('SETUP=' + JSON.stringify(setup))

  // Playground 진입 + 에이전트 선택
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(NAME, { exact: false }).first().click()
  await page.waitForTimeout(600)
  check(await page.getByText(NAME, { exact: false }).first().isVisible().catch(() => false), `Playground에서 노드형 "${NAME}" 선택`)

  // 메시지 전송
  const box = page.locator('textarea').first()
  await box.click()
  await box.fill('테스트 입력입니다. 분석하고 요약해줘.')
  await page.waitForTimeout(200)
  await box.press('Enter')
  // 응답(트레이스 칩) 대기
  const chip = page.getByText(/\d+\s*mem/).last()
  const arrived = await chip.waitFor({ state: 'visible', timeout: 60000 }).then(() => true).catch(() => false)
  check(arrived, '응답 도착(트레이스 칩)')
  if (arrived) await chip.click({ timeout: 8000 })
  await page.waitForTimeout(700)

  // 인스펙터 스크린샷 + 텍스트 확인
  await page.screenshot({ path: `${OUT}-inspector.png`, fullPage: false })
  const body = await page.locator('#root').innerText().catch(() => '')
  check(/분석/.test(body) && /요약/.test(body), '인스펙터에 노드 이름(분석·요약) 표면')
  check(/실행 흐름/.test(body), '인스펙터에 "실행 흐름" 섹션 존재')
  // 노드 순서: 분석이 요약보다 먼저 나타나는가(텍스트 위치)
  const iA = body.indexOf('분석'), iS = body.indexOf('요약')
  check(iA >= 0 && iS >= 0 && iA < iS, `노드 순서 표시(분석→요약, iA=${iA} iS=${iS})`)
  check(!/sk-[A-Za-z0-9_-]{6,}/.test(body), '화면에 sk- 토큰 없음(비밀 미표면)')
  // 스펙 262 — clean 노드 요약이 사람 말("이전 맥락 N개 정리")로, 내부어 "remove" 미노출
  check(/이전 맥락 \d+개 정리/.test(body), '요약 노드 격리 노트 사람말 표시(이전 맥락 N개 정리)')
  check(!/remove\s*\/\s*remove/.test(body), '"remove / remove" 내부어 미노출')
  log('shot: ' + OUT + '-inspector.png')

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: false }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
