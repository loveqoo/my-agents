/* 모델 폼 능력·설정 중복 제거 e2e(스펙 409) — 사용자 불만 "스트리밍·thinking이 두 번씩 나온다".
   프로바이더·모델 화면 → 모델 행의 '능력·설정' 팝오버 → 능력당 한 블록(능력 토글 + 요청 기본값)만,
   옛 중복 행("스트리밍으로 호출"·"thinking 켜서 호출")은 사라졌음을 단언.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright node tests/browser/verify-409-model-form.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.argv[2] ?? '/tmp/verify-409-model-form.png'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await ctx.newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }
try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.waitForTimeout(1500)
  // 프로바이더·모델 메뉴로 이동(사이드 접힘 대비 첫 버튼 토글).
  const menu = page.getByText('프로바이더·모델', { exact: true }).first()
  if (!(await menu.isVisible().catch(() => false))) {
    await page.locator('button').first().click()
    await page.waitForTimeout(600)
  }
  await menu.waitFor({ timeout: 10000 })
  await menu.click()
  await page.waitForTimeout(1500)
  // 첫 '능력·설정' 버튼 열기.
  const capsBtn = page.getByRole('button', { name: '능력·설정' }).first()
  await capsBtn.waitFor({ timeout: 10000 })
  await capsBtn.click()
  await page.waitForTimeout(800)
  // 팝오버 텍스트 수집(role=tooltip/popover 콘텐츠는 antd Popover가 body에 렌더).
  const body = await page.locator('body').innerText()
  ok(body.includes('스트리밍 지원'), "① 능력 토글 '스트리밍 지원' 존재(사실 층)")
  ok(body.includes('Thinking 모드 지원'), "② 능력 토글 'Thinking 모드 지원' 존재")
  ok(body.includes('요청 기본값'), "③ 능력 ON이면 '요청 기본값' 단일 컨트롤(중복 아님)")
  // 옛 중복 행이 사라졌는가(핵심 — 두 번씩 나오던 것).
  ok(!body.includes('스트리밍으로 호출'), "④ 옛 중복 행 '스트리밍으로 호출' 소멸")
  ok(!body.includes('thinking 켜서 호출'), "⑤ 옛 중복 행 'thinking 켜서 호출' 소멸")
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT', OUT)
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
} finally {
  await browser.close()
}
console.log(fails.length ? `VERIFY409_FORM_FAIL(${fails.length})` : 'VERIFY409_FORM_OK')
process.exit(fails.length ? 1 : 0)
