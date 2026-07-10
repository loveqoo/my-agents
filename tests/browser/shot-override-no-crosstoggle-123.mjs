/* 스펙 123 회귀 — 오버라이드 드로어에서 그룹 헤더 클릭이 다른 그룹 체크박스를 오토글하지 않는다.
   (근인: Field가 <label>로 그룹을 감싸 label→첫 하위 컨트롤로 click 전달. group prop으로 <div> 전환.)
   검증: (H) 사용자 기억 헤더 클릭 → 도구 체크박스 상태 불변, (T) 실제 체크박스 토글은 정상 동작,
   (S) Temperature 라벨 클릭 → Switch 불변. 시스템 Chrome.
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-override-no-crosstoggle-123.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/override-no-crosstoggle-123.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1200, height: 1100 } })
const page = await ctx.newPage()
const rand = Math.random().toString(36).slice(2, 8)
const MCP = `xmcp-${rand}`, ORCH = `x-orch-${rand}`
const cleanup = { agents: [], mcps: [] }

// 도구 그룹 체크박스들의 checked 상태 배열.
async function toolChecks(drawer) {
  const rows = drawer.locator('.ant-checkbox-wrapper')
  const n = await rows.count(); const out = []
  for (let i = 0; i < n; i++) {
    const r = rows.nth(i)
    const txt = (await r.textContent().catch(() => ''))?.trim()
    if (txt && !txt.includes('사용자 기억')) out.push((await r.getAttribute('class') ?? '').includes('ant-checkbox-wrapper-checked'))
  }
  return out
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  const mr = await page.request.post(`${URL}/api/mcp-servers`, { data: { name: MCP, source: 'local', transport: 'http', url: 'http://127.0.0.1:9/mcp' } })
  const mcp = await mr.json(); if (mcp?.id) cleanup.mcps.push(mcp.id)
  const or = await page.request.post(`${URL}/api/agents`, { data: { name: ORCH, config: { model: 'mock-llm', persona: '', impl: 'orchestrate', capabilities: [`mcp:${MCP}`] } } })
  const o = await or.json(); if (o?.id) cleanup.agents.push(o.id)

  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(ORCH, { exact: false }).first().click()
  await page.waitForTimeout(500)
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')
  // 스펙 249: 드로어=Steps 2단계 — 피커·세부는 1단계에 있다(273 갱신).
  await drawer.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)

  // (H) 그룹 헤더 클릭이 도구 체크박스를 오토글하지 않는다.
  const before = await toolChecks(drawer)
  await drawer.locator('.ant-collapse-header', { hasText: '사용자 기억' }).first().click()
  await page.waitForTimeout(400)
  const after = await toolChecks(drawer)
  check(JSON.stringify(before) === JSON.stringify(after),
        `H 사용자 기억 헤더 클릭 → 도구 체크박스 불변 (before=${JSON.stringify(before)} after=${JSON.stringify(after)})`)
  await page.screenshot({ path: OUT, fullPage: true })

  // (T) 실제 체크박스 토글은 정상 — local-tools를 직접 클릭하면 그 항목만 체크된다.
  const localRow = drawer.locator('.ant-checkbox-wrapper', { hasText: 'local-tools' }).first()
  const wasChecked = (await localRow.getAttribute('class') ?? '').includes('ant-checkbox-wrapper-checked')
  await localRow.click()
  await page.waitForTimeout(300)
  const nowChecked = (await localRow.getAttribute('class') ?? '').includes('ant-checkbox-wrapper-checked')
  check(wasChecked !== nowChecked, `T 실제 체크박스 클릭은 그 항목을 토글 (${wasChecked}→${nowChecked})`)

  // (S) Temperature 라벨 클릭 → Switch 불변 — 세부는 1단계에 평면 나열(스펙 249, 접이식 소멸).
  const sw = drawer.locator('.ant-switch').first()
  const swBefore = (await sw.getAttribute('aria-checked').catch(() => null))
  await drawer.getByText('Temperature', { exact: true }).first().click()
  await page.waitForTimeout(300)
  const swAfter = (await sw.getAttribute('aria-checked').catch(() => null))
  check(swBefore === swAfter, `S Temperature 라벨 클릭 → Switch 불변 (${swBefore}→${swAfter})`)

  console.log('SHOT', OUT)
} catch (e) {
  console.error('ERROR', e.message)
  try { await page.screenshot({ path: OUT, fullPage: true }) } catch {}
  fails.push('exception: ' + e.message)
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  for (const id of cleanup.mcps) { try { await page.request.delete(`${URL}/api/mcp-servers/${id}`) } catch {} }
  await browser.close()
  if (_fx) _fx.teardown?.()
  console.log(`\n${fails.length === 0 ? 'ALL PASS' : fails.length + ' FAIL'}`)
  process.exit(fails.length === 0 ? 0 : 1)
}
