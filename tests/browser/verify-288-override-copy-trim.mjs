/* 노드형 오버라이드 폼 문구 다이어트 검증 (스펙 287 후속).
   ① 오버라이드 드로어: 라벨 "노드 (프롬프트·모델·도구를 이 대화에서만 변경)" 부재,
      설명문 "노드를 위에서 아래로 순서대로..." 부재, 힌트 "노드 추가·삭제·순서는..."만 존재.
   ② 에이전트 편집(저작) 화면: 설명문은 그대로 존재(저작 안내는 유지).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/verify-288-override-copy-trim.mjs */
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
const AGENT = 'ov-288-' + Date.now().toString(36)
const cleanup = { agents: [] }
const DESC = '노드를 위에서 아래로 순서대로'
const LABEL = '프롬프트·모델·도구를 이 대화에서만 변경'
const HINT = '노드 추가·삭제·순서는 여기서 바꿀 수 없습니다'

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  const ar = await page.request.post(`${URL}/api/agents`, {
    data: { name: AGENT, config: { model: 'mock-llm', persona: '', impl: 'pipeline', mcps: [],
      nodes: [
        { name: 'n1', prompt: '분석해라', model: 'mock-llm', tools: [] },
        { name: 'n2', prompt: '요약해라', model: 'mock-llm', tools: [] },
      ] } },
  })
  const a = await ar.json()
  check(ar.ok(), `테스트 에이전트 생성 (${ar.status()})`)
  if (a?.id) cleanup.agents.push(a.id)

  // ── ① 오버라이드 드로어 ──
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(AGENT, { exact: false }).first().click()
  await page.waitForTimeout(600)
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')

  check((await drawer.getByText(LABEL, { exact: false }).count()) === 0, `① 라벨 "노드 (${LABEL})" 부재`)
  check((await drawer.getByText(DESC, { exact: false }).count()) === 0, `① 설명문 "${DESC}..." 부재`)
  check((await drawer.getByText(HINT, { exact: false }).count()) === 1, `① 힌트 "${HINT}..." 1건 존재`)
  check((await drawer.getByText('n1', { exact: true }).count()) > 0, `① 노드 카드는 그대로(n1)`)
  await page.screenshot({ path: 'tests/browser/out-288-override-drawer.png', fullPage: false })

  // ── ② 저작(새 에이전트 → 노드형) 화면 — 설명문 유지 ──
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  await page.getByRole('menuitem', { name: '에이전트' }).click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(600)
  const form = page.getByRole('dialog')
  await form.getByPlaceholder('예: research-assistant').fill('probe-288')
  await form.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
  await form.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(600)
  check((await form.getByText(DESC, { exact: false }).count()) >= 1, `② 저작 화면에는 설명문 유지`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
