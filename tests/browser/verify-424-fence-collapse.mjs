/* 스펙 424 검증 — 첨부 턴을 만든 뒤 **세션 재로드** 시 유저 말풍선이 접힌 형태(질문+📎)로
   보이는지(펜스 원문 노출 0). 표면 2곳: 플레이그라운드 재로드 + 세션 상세.
   실행: PLAYWRIGHT_DIR=<pw> node tests/browser/verify-424-fence-collapse.mjs */
import fs from 'node:fs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
fs.mkdirSync(OUT, { recursive: true })

const QMARK = 'V424질문마커 — 첨부 요약해줘'
const TMP = `${OUT}/v424-note.txt`
fs.writeFileSync(TMP, '첨부 검증용 본문입니다. 코드 예시와 지시문이 섞여 있어도 표시는 접혀야 한다.')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }

const login = async () => {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForTimeout(1500)
  const needLogin = await page.getByText('my-agents 로그인', { exact: true }).isVisible().catch(() => false)
  if (needLogin) {
    await page.getByPlaceholder('you@example.com').fill(EMAIL)
    await page.getByPlaceholder('비밀번호').fill(PASSWORD)
    await page.getByRole('button', { name: '로그인' }).click()
    await page.waitForTimeout(1200)
  }
}
const gotoPlayground = async () => {
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  // 리로드 후엔 선택이 유지될 수 있음 — 이미 personal-secretary면 스킵.
  const already = await page
    .locator('button')
    .filter({ hasText: 'personal-secretary' })
    .count()
  if (already > 0) return
  const combo = page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first()
  await combo.click()
  await page.getByText('personal-secretary', { exact: false }).first().click()
  await page.waitForTimeout(1000)
}

try {
  await login()
  await gotoPlayground()

  // ① 첨부 턴 생성(라이브)
  await page.locator('input[type="file"]').setInputFiles(TMP)
  await page.getByText('v424-note.txt', { exact: false }).waitFor({ timeout: 10000 })
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill(QMARK)
  await input.press('Enter')
  // 응답 완료 대기 — 어시스턴트 말풍선 등장(내용 무관, 영속만 필요)
  await page.waitForTimeout(1000)
  await page.getByText(QMARK, { exact: false }).first().waitFor({ timeout: 60000 })
  await page.waitForTimeout(8000) // 스트림 종료·영속 여유
  ok(true, '① 첨부 턴 생성(라이브)')

  // ② 페이지 리로드 → 세션 재선택 → 접힘 단언
  // vite dev는 HMR 웹소켓이 늘 열려 있어 networkidle이 오지 않는다 — DOM 로드로 대기.
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await login()
  await gotoPlayground()
  const sessBtn = page.locator('button').filter({ hasText: /세션|sess-/ }).first()
  await page.screenshot({ path: `${OUT}/v424-debug-before-open.png` })
  await sessBtn.click()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/v424-debug-dropdown.png` })
  // 항목 실물: 미리보기 + "…<hash> · 1턴 · 활성 · 시각" 메타줄 — 최신(첫) 행을 메타로 잡는다.
  await page.getByText(/· 1턴 ·|1턴/).first().click({ timeout: 8000 })
  await page.waitForTimeout(2000)
  const body = await page.locator('body').innerText()
  ok(!body.includes('⟦첨부'), '② 재로드 말풍선에 펜스 원문 없음(⟦첨부 0건)')
  ok(!body.includes('참고용 **데이터**'), '② 선언문도 노출 없음')
  ok(body.includes(QMARK), '② 질문 텍스트 보존')
  ok(body.includes('📎') && body.includes('v424-note.txt'), '② 📎 파일명 라인 표시')
  await page.screenshot({ path: `${OUT}/v424-reload.png` })

  // ③ 세션 상세(관리 화면)도 접힘
  await page.getByText('세션', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  await page.getByText(/sess-[0-9a-f]{8}/).first().click()
  await page.waitForTimeout(1500)
  const body2 = await page.locator('body').innerText()
  ok(!body2.includes('⟦첨부'), '③ 세션 상세에도 펜스 원문 없음')
  await page.screenshot({ path: `${OUT}/v424-sessions.png` })
  console.log(fails.length ? `\nFAIL ${fails.length}` : '\nVERIFY424_OK')
  process.exitCode = fails.length ? 1 : 0
} catch (e) {
  ok(false, `예외: ${e.message}`)
  process.exitCode = 1
} finally {
  await browser.close()
}
