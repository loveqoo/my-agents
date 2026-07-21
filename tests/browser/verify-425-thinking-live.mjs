/* 스펙 425 검증 — thinking 모드 라이브 + 첨부 재로드 접힘(424)의 결합 실증.
   흐름: 오버라이드(세션 층)에서 Thinking 켬 → 첨부 + 신선 질문(서버 프롬프트 캐시 회피 — 고유
   접미 필수, 스펙 425 교훈) → 사고 과정 패널 단언 → 페이지 재로드 → 세션 재선택 → 접힘 단언.
   실행: PLAYWRIGHT_DIR=<pw> node tests/browser/verify-425-thinking-live.mjs */
import fs from 'node:fs'
import crypto from 'node:crypto'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
fs.mkdirSync(OUT, { recursive: true })

const NONCE = crypto.randomBytes(3).toString('hex')
const QMARK = `V425질문마커-${NONCE} — 첨부의 숫자 두 개를 더하면? 계산 과정을 생각한 뒤 답해줘.`
const TMP = `${OUT}/v425-note.txt`
fs.writeFileSync(TMP, `검증 문서(${NONCE}): 첫째 숫자는 347, 둘째 숫자는 588 이다.`)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }

const login = async () => {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForTimeout(1500)
  const need = await page.getByText('my-agents 로그인', { exact: true }).isVisible().catch(() => false)
  if (need) {
    await page.getByPlaceholder('you@example.com').fill(EMAIL)
    await page.getByPlaceholder('비밀번호').fill(PASSWORD)
    await page.getByRole('button', { name: '로그인' }).click()
    await page.waitForTimeout(1500)
  }
}
const gotoPlayground = async () => {
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  if ((await page.locator('button').filter({ hasText: 'personal-secretary' }).count()) > 0) return
  const combo = page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first()
  await combo.click()
  await page.getByText('personal-secretary', { exact: false }).first().click()
  await page.waitForTimeout(1000)
}

try {
  await login()
  await gotoPlayground()

  // ① 오버라이드(세션 층)에서 Thinking 명시 켬 — 2단계 마법사
  await page.getByText('오버라이드', { exact: false }).first().click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(600)
  const thinkSelect = page
    .getByText('Thinking 모드', { exact: true })
    .locator('xpath=following::div[contains(@class,"ant-select")][1]')
  await thinkSelect.click()
  await page.waitForTimeout(400)
  await page.getByRole('option', { name: /^켬$/ }).click().catch(async () => {
    await page.locator('.ant-select-dropdown:visible').getByText(/^켬$/).first().click()
  })
  await page.getByRole('button', { name: /적용/ }).click()
  await page.waitForTimeout(1000)
  ok(true, '① 오버라이드 Thinking=켬 적용(세션 층 — 스펙 370 핀과 독립)')

  // ② 첨부 + 신선 질문 전송 → 사고 과정 패널(라이브)
  await page.locator('input[type="file"]').setInputFiles(TMP)
  await page.getByText('v425-note.txt', { exact: false }).waitFor({ timeout: 10000 })
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill(QMARK)
  await input.press('Enter')
  await page.getByText('사고 과정', { exact: false }).first().waitFor({ timeout: 120000 })
  ok(true, '② 사고 과정 패널 표시(thinking 라이브 실증)')
  // 스트림 완료 대기 — 답(935)이 본문에 실제로 뜬 뒤에야 영속·세션 목록 반영이 끝난다(고정 대기 금지).
  await page.getByText('935', { exact: false }).first().waitFor({ timeout: 120000 })
  await page.waitForTimeout(4000)
  await page.screenshot({ path: `${OUT}/v425-live-thinking.png` })

  // ③ 재로드 → 세션 재선택 → 접힘 단언(424 결합)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await login()
  await gotoPlayground()
  await page.locator('button').filter({ hasText: /세션|sess-/ }).first().click()
  await page.waitForTimeout(800)
  // 세션 선택은 고유 마커로(서버 미리보기가 질문을 표시 — 424 수리) — '1턴' 첫 매치는 남의 세션을 집는다.
  await page.getByText(new RegExp(`V425질문마커-${NONCE}`)).first().click({ timeout: 8000 })
  await page.waitForTimeout(2000)
  const body = await page.locator('body').innerText()
  ok(!body.includes('⟦첨부'), '③ 재로드 말풍선에 펜스 원문 없음')
  ok(!body.includes('참고용 **데이터**'), '③ 선언문 노출 없음')
  ok(body.includes(`V425질문마커-${NONCE}`), '③ 질문 텍스트 보존')
  ok(body.includes('📎') && body.includes('v425-note.txt'), '③ 📎 파일명 라인 표시')
  await page.screenshot({ path: `${OUT}/v425-reload.png` })
  console.log(fails.length ? `\nFAIL ${fails.length}` : '\nVERIFY425_OK')
  process.exitCode = fails.length ? 1 : 0
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: `${OUT}/v425-debug-fail.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
