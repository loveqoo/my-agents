/* 스펙 122 검증 — 조율형 플레이그라운드 오버라이드에 MCP(capability) 표시. 시스템 Chrome.
   admin(vite :5173) 로그인 → API로 MCP 서버 + 조율형 에이전트(capabilities=[mcp:<서버>]) 시드·활성화 →
   Playground에서 그 에이전트 선택 → "오버라이드" 열기 → "이 대화에서 맡길 것"(조율형 kind-aware 분기)에
   설정한 MCP가 **체크된 상태로** 보이는지 확인(버그2: 예전엔 mcps만 봐서 누락됐음).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-orchestrator-override-122.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/orchestrator-override-122.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1200, height: 1100 } })
const page = await ctx.newPage()

const rand = Math.random().toString(36).slice(2, 8)
const MCP = `ovmcp-${rand}`
const AGENT = `ov-orch-${rand}`
const cleanup = { agents: [], mcps: [] }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // MCP 서버 시드(세션 쿠키 프록시 /api).
  const mcpRes = await page.request.post(`${URL}/api/mcp-servers`, {
    data: { name: MCP, source: 'local', transport: 'http', url: 'http://127.0.0.1:9/mcp' },
  })
  check(mcpRes.ok(), `S1 MCP 서버 시드 (status ${mcpRes.status()})`)
  const mcp = await mcpRes.json()
  if (mcp?.id) cleanup.mcps.push(mcp.id)

  // 조율형 에이전트 시드 — capabilities에 mcp:<서버>.
  const agRes = await page.request.post(`${URL}/api/agents`, {
    data: {
      name: AGENT,
      config: { model: 'mock-llm', prompt: '', impl: 'orchestrate', capabilities: [`mcp:${MCP}`] },
    },
  })
  check(agRes.ok(), `S2 조율형 에이전트 시드 (status ${agRes.status()})`)
  const agent = await agRes.json()
  if (agent?.id) cleanup.agents.push(agent.id)

  // 활성화(사용자 플로우 재현) — 버전 문자열은 시드 응답에서.
  const ver = agent.activeVersion ?? agent.version ?? (agent.versions?.[0]?.version) ?? '1'
  const actRes = await page.request.post(`${URL}/api/agents/${agent.id}/activate`, { data: { version: ver } })
  check(actRes.ok(), `S3 v${ver} 활성화 (status ${actRes.status()})`)

  // Playground로 이동(리로드 금지 — 뷰 상태는 메모리라 리로드하면 기본 뷰로 되돌아감).
  // Playground 마운트가 listAgents로 시드 에이전트를 새로 불러온다.
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)

  // 상단 에이전트 스위처(트리거 버튼)를 열고 시드 조율형 선택. 기본 활성은 첫 에이전트(Doc Translator)라 전환.
  const switcher = page.getByRole('button', { name: /Doc Translator/ }).first()
  check(await switcher.count() > 0, 'H0 에이전트 스위처 트리거 렌더')
  await switcher.click()
  await page.waitForTimeout(400)
  const agItem = page.getByText(AGENT, { exact: false }).first()
  check(await agItem.count() > 0, 'H1 스위처 목록에 조율형 에이전트 보임')
  await agItem.click()
  await page.waitForTimeout(500)

  // "오버라이드" 열기 — 버튼은 title="런타임 오버라이드"(compact면 아이콘만이라 title로 타깃).
  const ovBtn = page.locator('button[title*="오버라이드"]').first()
  check(await ovBtn.count() > 0, 'H1b 오버라이드 버튼 렌더')
  await ovBtn.click()
  await page.waitForTimeout(600)

  // 조율형 kind-aware 분기: 필드 라벨이 "이 대화에서 맡길 것"(직접형은 "쓸 것").
  const drawer = page.getByRole('dialog')
  check(await drawer.getByText('이 대화에서 맡길 것', { exact: true }).count() > 0,
        'H2 조율형 분기 렌더("이 대화에서 맡길 것")')

  // "도구" 그룹이 접혀 있으면 펼친다(선택된 항목이 안 보이면).
  if (await drawer.getByText(MCP, { exact: false }).count() === 0) {
    await drawer.getByText('도구', { exact: true }).first().click()
    await page.waitForTimeout(300)
  }
  check(await drawer.getByText(MCP, { exact: false }).count() > 0,
        `H3 오버라이드 패널에 설정한 MCP(${MCP}) 표시(예전엔 누락)`)
  // 그 MCP 행이 체크된 상태(antd: ant-checkbox-wrapper-checked). 설정한 capability가 선택돼 시드됨.
  const wrapper = drawer.locator('.ant-checkbox-wrapper', { hasText: MCP }).first()
  const cls = (await wrapper.count() > 0) ? (await wrapper.getAttribute('class')) ?? '' : ''
  check(cls.includes('ant-checkbox-wrapper-checked'),
        `H4 MCP capability가 체크된 상태(설정 반영, class=${cls || 'none'})`)

  await page.screenshot({ path: OUT, fullPage: true })
  console.log('SHOT', OUT)
} catch (e) {
  console.error('ERROR', e.message)
  try { await page.screenshot({ path: OUT, fullPage: true }); console.log('SHOT(err)', OUT) } catch {}
  fails.push('exception: ' + e.message)
} finally {
  // 정리: 에이전트 → MCP(참조 해제 후).
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  for (const id of cleanup.mcps) { try { await page.request.delete(`${URL}/api/mcp-servers/${id}`) } catch {} }
  await browser.close()
  if (_fx) _fx.teardown?.()
  console.log(`\n${fails.length === 0 ? 'ALL PASS' : fails.length + ' FAIL'}`)
  process.exit(fails.length === 0 ? 0 : 1)
}
