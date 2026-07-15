/* 스펙 122 회귀 — 플레이그라운드 오버라이드가 **에이전트 종류별로** 올바른 표면을 그리는지.
   직접형(default-ui): "이 대화에서 쓸 것"(mcps/memories), capabilities 아님.
   조율형(orchestrate): "이 대화에서 맡길 것"(capabilities).
   코드(source=code): read-only 안내(오버라이드 미적용).
   시스템 Chrome. 실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-override-by-kind-122.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/override-by-kind-122.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1200, height: 1100 } })
const page = await ctx.newPage()

const rand = Math.random().toString(36).slice(2, 8)
const MCP = `kmcp-${rand}`
const DIRECT = `k-direct-${rand}`
const ORCH = `k-orch-${rand}`
const CODE = `k-code-${rand}`
const cleanup = { agents: [], mcps: [] }

// 스위처를 열고 이름으로 에이전트 선택. 트리거는 아바타(.ant-avatar)를 가진 유일한 버튼(헤더 액션
// 버튼엔 아바타 없음). 메시지 버블 아바타는 button이 아니라 겹치지 않음.
async function selectAgent(name) {
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(name, { exact: false }).first().click()
  await page.waitForTimeout(500)
}

async function openOverride() {
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(500)
}
async function closeDrawer() {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(300)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 시드: MCP + 직접형(mcps에 담음) + 조율형(capabilities) + 코드(원격).
  const mcpRes = await page.request.post(`${URL}/api/mcp-servers`, {
    data: { name: MCP, source: 'local', transport: 'http', url: 'http://127.0.0.1:9/mcp' },
  })
  check(mcpRes.ok(), `S1 MCP 시드 (${mcpRes.status()})`)
  const mcp = await mcpRes.json(); if (mcp?.id) cleanup.mcps.push(mcp.id)

  const dRes = await page.request.post(`${URL}/api/agents`, {
    data: { name: DIRECT, config: { model: 'mock-llm', prompt: '', impl: '', mcps: [MCP] } },
  })
  check(dRes.ok(), `S2 직접형 시드 (${dRes.status()})`)
  const d = await dRes.json(); if (d?.id) cleanup.agents.push(d.id)

  const oRes = await page.request.post(`${URL}/api/agents`, {
    data: { name: ORCH, config: { model: 'mock-llm', prompt: '', impl: 'orchestrate', capabilities: [`mcp:${MCP}`] } },
  })
  check(oRes.ok(), `S3 조율형 시드 (${oRes.status()})`)
  const o = await oRes.json(); if (o?.id) cleanup.agents.push(o.id)

  // 코드 에이전트는 POST /agents로 source 지정이 안 되므로(런타임 등록 경로가 별도), 기존 시드
  // 데모인 "Doc Translator"(원격 SDK=source:code)로 read-only 경로를 검증한다.
  const CODE_EXISTING = 'Doc Translator'

  // Playground 진입(리로드 금지).
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)

  // ── 직접형: "쓸 것" + MCP, "맡길 것" 없음 ──
  await selectAgent(DIRECT)
  await openOverride()
  let drawer = page.getByRole('dialog')
  check(await drawer.getByText('이 대화에서 쓸 것', { exact: true }).count() > 0, 'D1 직접형=쓸 것 라벨')
  check(await drawer.getByText('이 대화에서 맡길 것', { exact: true }).count() === 0, 'D2 직접형에 맡길 것 없음(capabilities 누출 없음)')
  if (await drawer.getByText(MCP).count() === 0) { await drawer.getByText('도구', { exact: true }).first().click().catch(() => {}); await page.waitForTimeout(300) }
  check(await drawer.getByText(MCP).count() > 0, 'D3 직접형 도구에 mcps의 MCP 표시')
  await closeDrawer()

  // ── 조율형: "맡길 것" + capabilities ──
  await selectAgent(ORCH)
  await openOverride()
  drawer = page.getByRole('dialog')
  check(await drawer.getByText('이 대화에서 맡길 것', { exact: true }).count() > 0, 'O1 조율형=맡길 것 라벨')
  check(await drawer.getByText('이 대화에서 쓸 것', { exact: true }).count() === 0, 'O2 조율형에 쓸 것 없음')
  await page.screenshot({ path: OUT, fullPage: true })
  await closeDrawer()

  // ── 코드(기존 SDK 데모): read-only 안내 ──
  await selectAgent(CODE_EXISTING)
  await openOverride()
  drawer = page.getByRole('dialog')
  check(await drawer.getByText(/오버라이드 미적용|원격/).count() > 0, 'C1 코드=read-only 안내(오버라이드 미적용)')
  check(await drawer.getByText('이 대화에서 쓸 것', { exact: true }).count() === 0
        && await drawer.getByText('이 대화에서 맡길 것', { exact: true }).count() === 0,
        'C2 코드에 도구/위임 피커 없음')

  console.log('SHOT', OUT)
} catch (e) {
  console.error('ERROR', e.message)
  try { await page.screenshot({ path: OUT, fullPage: true }); console.log('SHOT(err)', OUT) } catch {}
  fails.push('exception: ' + e.message)
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  for (const id of cleanup.mcps) { try { await page.request.delete(`${URL}/api/mcp-servers/${id}`) } catch {} }
  await browser.close()
  if (_fx) _fx.teardown?.()
  console.log(`\n${fails.length === 0 ? 'ALL PASS' : fails.length + ' FAIL'}`)
  process.exit(fails.length === 0 ? 0 : 1)
}
