/* 스펙 109 검증 — 플레이그라운드 오버라이드에도 같은 효율 피커·세부설정 접힘 반영. 시스템 Chrome.
   실행: ADMIN_URL=http://localhost:5173 PLAYWRIGHT_DIR=<abs> node tests/browser/shot-override-109.mjs /tmp/override-109 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://localhost:5173'
const OUT = process.argv[2] ?? '/tmp/override-109'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let fails = 0
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails++ }
const AGENT = 'ov109-' + Date.now().toString(36)
const cleanup = { agents: [] }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  // ui(web) 직접형 에이전트를 직접 만든다 — 시드 에이전트명 의존은 낡는다(273 갱신).
  const ar = await page.request.post(`${URL}/api/agents`, {
    data: { name: AGENT, config: { model: 'mock-llm', persona: '테스트용', mcps: [], memories: [] } },
  })
  const a = await ar.json(); if (a?.id) cleanup.agents.push(a.id)

  // Playground 진입 + 에이전트 선택.
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(AGENT, { exact: false }).first().click()
  await page.waitForTimeout(800)

  // 런타임 오버라이드 버튼(title) 클릭 → 드로어 open.
  const ovBtn = page.locator('button[title*="오버라이드"]').first()
  check(await ovBtn.count() > 0, 'P1 런타임 오버라이드 버튼 존재')
  await ovBtn.click()
  await page.waitForTimeout(800)

  const drawer = page.locator('.ant-drawer-body')
  const dtext = await drawer.innerText().catch(() => '')
  // 외부/코드 에이전트면 read-only — ui 에이전트여야 폼. 안내로 판별.
  const readonly = /오버라이드 미적용/.test(dtext)
  if (readonly) {
    log('  --  현재 에이전트가 원격(code/external) — 오버라이드 폼 없음. ui 에이전트 필요.')
    await page.screenshot({ path: `${OUT}-readonly.png`, fullPage: true })
  }

  if (!readonly) {
    // 스펙 249: 드로어=Steps 2단계(0=무엇으로, 1=쓸 것·세부 평면). "다음"으로 1단계 이동.
    await page.getByRole('dialog').getByRole('button', { name: '다음' }).click()
    await page.waitForTimeout(500)
    const d1 = await drawer.innerText().catch(() => '')
    check(d1.includes('이 대화에서 쓸 것'), 'P2 1단계에 "이 대화에서 쓸 것" 피커')
    check(d1.includes('Temperature'), 'P3 세부 평면 나열(Temperature 노출, 스펙 249)')
    // 피커 그룹 = 도구만(스펙 273 — 기억은 공용 컨트롤로 이동). 단기/장기 라벨은 세부 쪽에.
    const heads = (await drawer.locator('.ant-collapse-header').allInnerTexts()).join(' | ')
    check(/도구/.test(heads) && !/^기억|\| 기억/.test(heads), `P5 피커 그룹=도구만·기억 그룹 없음 (=${heads})`)
    check(d1.includes('단기 기억') && d1.includes('장기 기억'), 'P5b 공용 단기/장기 기억 컨트롤(스펙 271/273)')
    // 기술 id 부재.
    check(!/mcp:|memory:|tool:|mem:/.test(d1), 'P6 기술 id 노출 없음')
  } else {
    check(readonly, 'P2 원격 read-only 안내')
  }

  await page.screenshot({ path: `${OUT}.png`, fullPage: true })
  log('SHOT ' + OUT + '.png')
  log(fails === 0 ? 'OVERRIDE109_OK' : `OVERRIDE109_FAIL(${fails})`)
  if (fails) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
  if (_fx) _fx.teardown?.()
}
