/* 드래그&드롭 첨부(스펙 406) 기능 e2e — 합성 DataTransfer 드롭 → 선택 모달 →
   "이번 대화만" 경로 관통(404 칩·응답 토큰). login/nav는 404/405 스크립트와 동일.

   실행: PLAYWRIGHT_DIR=<pw> node tests/browser/verify-406-dragdrop.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const VW = Number(process.env.VW ?? 1280)
const OUT = process.argv[2] ?? `/tmp/verify-406-dragdrop-${VW}.png`

const TOKEN = 'DELTA-수박-7749'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 900 } })
const page = await ctx.newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  const pgMenu = page.getByText('Playground', { exact: true }).first()
  await page.waitForTimeout(1200)
  if (!(await pgMenu.isVisible().catch(() => false))) {
    await page.locator('button').first().click()
    await page.waitForTimeout(600)
  }
  await pgMenu.waitFor({ timeout: 10000 })
  await pgMenu.click()
  await page.waitForTimeout(2000)
  const combo = page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first()
  await combo.click()
  await page.getByText('personal-secretary', { exact: false }).first().click()
  await page.waitForTimeout(1000)

  // ① 합성 DataTransfer로 드래그 진입 → 오버레이 확인
  const dt = await page.evaluateHandle((tok) => {
    const d = new DataTransfer()
    d.items.add(new File([`드롭 문서의 비밀 코드는 ${tok} 이다.`], 'drop-note.txt', { type: 'text/plain' }))
    return d
  }, TOKEN)
  const zone = page.getByPlaceholder(/에게 메시지/) // 드롭 존 내부 요소면 어디든 버블링
  await zone.dispatchEvent('dragenter', { dataTransfer: dt })
  await page.getByText('여기에 놓아 첨부', { exact: false }).waitFor({ timeout: 5000 })
  ok(true, '① 드래그 진입 → 오버레이 표시')
  await page.screenshot({ path: OUT.replace('.png', '-overlay.png') })

  // ② 드롭 → 선택 모달
  await zone.dispatchEvent('drop', { dataTransfer: dt })
  await page.getByText('첨부 방식 선택', { exact: true }).waitFor({ timeout: 5000 })
  ok(true, '② 드롭 → 선택 모달(이번 대화만/지식으로 저장)')

  // ③ "이번 대화만" → 404 흐름 관통(칩→질문→토큰 응답)
  await page.getByRole('button', { name: '이번 대화만 첨부' }).click()
  await page.getByText('drop-note.txt', { exact: false }).waitFor({ timeout: 10000 })
  ok(true, '③ 첨부 칩 생성(404 흐름 합류)')
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill('드롭한 문서의 비밀 코드가 뭐야? 코드만 정확히 답해줘.')
  await input.press('Enter')
  await page.getByText(TOKEN, { exact: false }).first().waitFor({ timeout: 120000 })
  ok(true, `④ 응답이 드롭 문서 속 토큰(${TOKEN})을 근거로 답함`)

  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT', OUT)
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
} finally {
  await browser.close()
}
console.log(fails.length ? `VERIFY406_BROWSER_FAIL(${fails.length})` : 'VERIFY406_BROWSER_OK')
process.exit(fails.length ? 1 : 0)
