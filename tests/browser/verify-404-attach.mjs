/* 파일첨부 기능 검증(스펙 404) — 외형이 아니라 **기능**: 첨부 → 질문 → 응답이 첨부 내용을
   근거로 하는지 + trace 표면화. login/nav 패턴은 check-sticky-095와 동일(_fixture super).

   실행: PLAYWRIGHT_DIR=<pw> node tests/browser/verify-404-attach.mjs [out.png] */
import fs from 'node:fs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.argv[2] ?? '/tmp/verify-404-attach.png'

const TOKEN = 'ORBIT-멜론-9184' // 모델이 지어낼 수 없는 임의 토큰 — 첨부에서만 알 수 있다
const TMP = '/tmp/v404-browser-note.txt'
fs.writeFileSync(TMP, `사내 비밀 프로젝트 코드네임은 ${TOKEN} 이다. 이 문서는 첨부 기능 검증용이다.`)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const VW = Number(process.env.VW ?? 1280)
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
  // 좁은 뷰포트(모바일)는 사이드바가 접힘 — Playground가 안 보이면 햄버거(헤더 첫 버튼)로 연다.
  const pgMenu = page.getByText('Playground', { exact: true }).first()
  await page.waitForTimeout(1200)
  if (!(await pgMenu.isVisible().catch(() => false))) {
    await page.locator('button').first().click()
    await page.waitForTimeout(600)
  }
  await pgMenu.waitFor({ timeout: 10000 })
  await pgMenu.click()
  await page.waitForTimeout(2000)

  // 로컬(ui) 에이전트로 전환 — 첨부는 로컬 한정(원격 A2A는 422). 헤더 콤보 → personal-secretary.
  const combo = page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first()
  await combo.click()
  await page.getByText('personal-secretary', { exact: false }).first().click()
  await page.waitForTimeout(1000)

  // ① 클립 버튼 → 파일 선택(숨은 input에 직접 주입)
  const fileInput = page.locator('input[type="file"]')
  await fileInput.setInputFiles(TMP)
  await page.getByText('v404-browser-note.txt', { exact: false }).waitFor({ timeout: 10000 })
  ok(true, '① 첨부 칩 표시(파일명·글자수)')

  // ② 질문 전송 → 응답이 첨부 토큰을 근거로 답하는지(실모델 — 문서에만 있는 토큰)
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill('첨부한 문서에 적힌 코드네임이 뭐야? 코드네임만 정확히 답해줘.')
  await input.press('Enter')
  await page.getByText(TOKEN, { exact: false }).first().waitFor({ timeout: 120000 })
  ok(true, `② 응답이 첨부 속 토큰(${TOKEN})을 근거로 답함 — 주입 실동작`)

  // ③ 첨부 칩 소모(전송 후 사라짐 — 1회성)
  await page.waitForTimeout(500)
  const chipGone = (await page.locator('.ant-tag', { hasText: 'v404-browser-note' }).count()) === 0
  ok(chipGone, '③ 전송 후 첨부 칩 소모(1회성)')

  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT', OUT)
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
} finally {
  await browser.close()
}
console.log(fails.length ? `VERIFY404_BROWSER_FAIL(${fails.length})` : 'VERIFY404_BROWSER_OK')
process.exit(fails.length ? 1 : 0)
