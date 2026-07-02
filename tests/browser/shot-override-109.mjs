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

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  // Playground 진입.
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  // ui(web) 에이전트 선택 — 기본 첫 에이전트가 code면 오버라이드가 read-only. 상단 선택기 드롭다운 열기.
  await page.getByText('Doc Translator', { exact: true }).first().click()
  await page.waitForTimeout(500)
  await page.getByText('Research Assistant', { exact: true }).first().click()
  await page.waitForTimeout(800)

  // 런타임 오버라이드 버튼(title) 클릭 → 드로어 open.
  const ovBtn = page.locator('[title^="런타임 오버라이드"]').first()
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

  check(dtext.includes('이 대화에서 쓸 것') || readonly, 'P2 오버라이드에 "이 대화에서 쓸 것" 피커(또는 원격 read-only)')
  if (!readonly) {
    check(dtext.includes('세부 설정 (선택)'), 'P3 오버라이드 "세부 설정 (선택)" 접이식')
    check(!dtext.includes('Temperature'), 'P4 세부설정 기본 접힘(Temperature 숨김)')
    // 하는 일 그룹 = 도구·기억.
    const heads = (await drawer.locator('.ant-collapse-header').allInnerTexts()).join(' | ')
    check(/도구/.test(heads) && /기억/.test(heads), `P5 피커 그룹=도구·기억 (=${heads})`)
    // 기술 id 부재.
    check(!/mcp:|memory:|tool:|mem:/.test(dtext), 'P6 기술 id 노출 없음')
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
  await browser.close()
}
