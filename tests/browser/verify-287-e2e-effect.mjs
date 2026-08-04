/* 스펙 287 종단 효과(브라우저 한 바퀴) — UI에서 노드 도구 체크 해제 → 적용 → 응답 트레이스에서
   echo 도구 호출 소멸까지. (요청 payload가 아니라 **응답 효과**를 단언 — UI 검증은 기능적으로.) */
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
const AGENT = 'ov287e-' + Date.now().toString(36)
const cleanup = []

// chat SSE 응답 본문 수집(스트림 종료 후 전체 텍스트) — trace 이벤트의 mcp 호출을 실측.
const chatResponses = []
page.on('response', async (res) => {
  if (res.request().method() === 'POST' && /\/api\/agents\/[^/]+\/chat/.test(res.url())) {
    try { chatResponses.push(await res.text()) } catch {}
  }
})
const echoCallsIn = (sse) => (sse.match(/"tool":\s*"echo"/g) || []).length

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  const ar = await page.request.post(`${URL}/api/agents`, {
    data: { name: AGENT, config: { model: 'mock-llm', prompt: '', impl: 'pipeline', mcps: ['local-tools'],
      nodes: [{ name: 'n1', prompt: '요청을 처리해라', model: 'mock-llm', tools: ['local-tools__echo'] }] } },
  })
  const a = await ar.json(); if (a?.id) cleanup.push(a.id)
  check(ar.ok(), `픽스처 생성 (${ar.status()})`)

  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(AGENT, { exact: false }).first().click()
  await page.waitForTimeout(600)

  // ① 기준선 — 오버라이드 없이 echo 언급 → 응답 trace에 echo 호출 존재
  const box = () => page.locator('textarea').first()
  await box().fill('echo 테스트를 해줘')
  await box().press('Enter')
  await page.waitForTimeout(3000)
  check(chatResponses.length >= 1 && echoCallsIn(chatResponses.at(-1)) > 0,
    `① 기준선: 응답 trace에 echo 호출 (got ${chatResponses.length ? echoCallsIn(chatResponses.at(-1)) : 'no-response'})`)

  // ② 드로어에서 노드 1 도구의 echo 체크 해제 → 적용
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(800)
  const drawer = page.getByRole('dialog')
  await drawer.locator('.ant-collapse-expand-icon').first().click() // 노드 1 펼침
  await page.waitForTimeout(500)
  // 도구 아코디언(ToolTree)은 **선택 도구가 있으면 기본 펼침**(defaultActiveKey) — 무조건 클릭하면
  // 열린 걸 닫는다(실측). 트리가 안 보일 때만 연다.
  if ((await drawer.locator('.ant-tree:visible').count()) === 0) {
    await drawer.locator('.ant-collapse .ant-collapse .ant-collapse-header').filter({ hasText: '도구' }).first().click()
    await page.waitForTimeout(500)
  }
  // 1-depth 초기화(스펙 278) — 서버 노드를 먼저 펼쳐야 리프가 렌더된다.
  const srvNode = drawer.locator('.ant-tree-treenode', { has: page.getByText('local-tools', { exact: true }) }).first()
  await srvNode.locator('.ant-tree-switcher').first().click()
  await page.waitForTimeout(400)
  const echoNode = drawer.locator('.ant-tree-treenode', { has: page.getByText('echo', { exact: true }) }).first()
  await echoNode.locator('.ant-tree-checkbox').first().click() // 체크 해제
  await page.waitForTimeout(400)
  await drawer.getByRole('button', { name: /적용 — 새 대화/ }).click()
  await page.waitForTimeout(1000)

  // ③ 같은 질문 → 응답 trace에 echo 호출 0 + overrides.nodes applied
  await box().fill('echo 테스트를 해줘')
  await box().press('Enter')
  await page.waitForTimeout(3000)
  const last = chatResponses.at(-1) ?? ''
  check(chatResponses.length >= 2, `② 오버라이드 후 응답 수신 (n=${chatResponses.length})`)
  check(echoCallsIn(last) === 0, `③ 종단 효과: 오버라이드 후 echo 호출 0 (got ${echoCallsIn(last)})`)
  check(/"nodes":\s*\{"count":\s*1,\s*"status":\s*"applied"\}/.test(last), `③ 응답 trace.overrides.nodes=applied`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
