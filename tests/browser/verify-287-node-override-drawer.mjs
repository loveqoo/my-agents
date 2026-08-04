/* 노드형 오버라이드 드로어 검증 (스펙 287) — 필수 단언(UI 기능적).
   ① 노드형 표면: Steps=노드/세부, 노드 카드 2개(공용 NodeListEditor), 직접형 표면(시스템 프롬프트·
      도구 트리·장기 기억·Temperature) 부재.
   ② 구조 불변 모드: '+ 노드 추가'·'삭제'·이동(↑↓) 부재, 열어도 이름 Input 없음(읽기 전용).
   ③ 기능 왕복: 노드 1 프롬프트 수정 → 적용 → 실제 메시지 전송 시 POST /chat body.overrides에
      nodes(길이 2·수정 프롬프트) + 파생 풀(mcps) 배선.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-287-node-override-drawer.mjs */
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
const AGENT = 'ov-287-' + Date.now().toString(36)
const cleanup = { agents: [] }

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 노드형 픽스처 — 노드 2(n1=echo 도구, n2=없음).
  const ar = await page.request.post(`${URL}/api/agents`, {
    data: { name: AGENT, config: { model: 'mock-llm', prompt: '', impl: 'pipeline', mcps: ['local-tools'],
      nodes: [
        { name: 'n1', prompt: '분석해라', model: 'mock-llm', tools: ['local-tools__echo'] },
        { name: 'n2', prompt: '요약해라', model: 'mock-llm', tools: [] },
      ] } },
  })
  const a = await ar.json()
  check(ar.ok(), `테스트 에이전트 생성 (${ar.status()})`)
  if (a?.id) cleanup.agents.push(a.id)

  // Playground → 에이전트 선택 → 오버라이드 드로어
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(AGENT, { exact: false }).first().click()
  await page.waitForTimeout(600)
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')

  // ── ① 노드형 표면 ──
  const stepTitles = await drawer.locator('.ant-steps-item-title').allTextContents()
  check(stepTitles.includes('노드') && stepTitles.includes('세부'), `① Steps=노드/세부 (got ${JSON.stringify(stepTitles)})`)
  check((await drawer.getByText('n1', { exact: true }).count()) > 0 && (await drawer.getByText('n2', { exact: true }).count()) > 0, `① 노드 카드 2(n1·n2)`)
  check((await drawer.getByText('시스템 프롬프트', { exact: true }).count()) === 0, `① 직접형 표면(시스템 프롬프트) 부재`)

  // ── ② 구조 불변 모드 ──
  check((await drawer.getByRole('button', { name: /노드 추가/ }).count()) === 0, `② '+ 노드 추가' 부재`)
  check((await drawer.getByRole('button', { name: '삭제' }).count()) === 0, `② '삭제' 부재`)
  check((await drawer.getByRole('button', { name: '↑' }).count()) === 0, `② 이동(↑) 부재`)
  // 노드 1 펼침(collapsible=icon — 확장 아이콘 클릭) → 이름 Input 없음(읽기 전용 텍스트)
  await drawer.locator('.ant-collapse-expand-icon').first().click()
  await page.waitForTimeout(500)
  check((await drawer.getByPlaceholder(/노드 1 이름/).count()) === 0, `② 이름 Input 없음(읽기 전용)`)
  check((await drawer.locator('textarea').count()) > 0, `② 필드 편집은 가능(프롬프트 textarea 존재)`)

  // ── ③ 기능 왕복: 노드 1 프롬프트 수정 → 적용 → payload ──
  const NEW_PROMPT = '오버라이드된 지시 287'
  const ta = drawer.locator('textarea').first()
  await ta.fill(NEW_PROMPT)
  await page.waitForTimeout(300)
  // 세부(2단계): 단기 기억만 — Temperature·장기 기억·도구 트리 부재
  await drawer.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  check((await drawer.getByText('단기 기억', { exact: true }).count()) > 0, `① 세부=단기 기억(상속 원천)`)
  // Temperature 복귀(287 후속, 2026-07-10) — 실측상 노드형도 소비(pipeline.py:79 모든 노드 적용)
  check((await drawer.getByText('Temperature', { exact: true }).count()) > 0, `① 세부에 Temperature 존재(모든 노드 적용)`)
  check((await drawer.getByText('장기 기억', { exact: true }).count()) === 0, `① 세부에 장기 기억 부재(노드 소유)`)
  check((await drawer.locator('.ant-tree').count()) === 0, `① 도구 트리 부재(노드 소유)`)
  // Temperature 켬(0.7 기본) → 페이로드 동봉 확인용
  await drawer.locator('.ant-switch').first().click()
  await page.waitForTimeout(300)

  await drawer.getByRole('button', { name: /적용 — 새 대화/ }).click()
  await page.waitForTimeout(800)

  let chatBody = null
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/agents\/[^/]+\/chat/.test(req.url())) {
      try { chatBody = JSON.parse(req.postData() ?? 'null') } catch {}
    }
  })
  const box = page.locator('textarea').first()
  await box.fill('안녕')
  await box.press('Enter')
  await page.waitForTimeout(2500)

  const ov = chatBody?.overrides ?? null
  log('CHAT_BODY.overrides.nodes=' + JSON.stringify(ov?.nodes ?? null))
  check(Array.isArray(ov?.nodes) && ov.nodes.length === 2, `③ overrides.nodes 길이 2 (got ${ov?.nodes?.length})`)
  check(ov?.nodes?.[0]?.prompt === NEW_PROMPT, `③ 노드 1 프롬프트 오버라이드 배선 (got ${JSON.stringify(ov?.nodes?.[0]?.prompt)})`)
  check(ov?.nodes?.[1]?.prompt === '요약해라', `③ 노드 2=저장값 유지`)
  check(Array.isArray(ov?.mcps) && ov.mcps.includes('local-tools'), `③ 파생 풀 mcps 동봉 (got ${JSON.stringify(ov?.mcps)})`)
  check(ov?.temperature === 0.7, `③ temperature 오버라이드 동봉 (got ${JSON.stringify(ov?.temperature)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
