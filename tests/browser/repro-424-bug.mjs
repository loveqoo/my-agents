/* 스펙 424 버그 재현(수리 revert 상태) — 첨부+thinking 세션을 재로드하면 내부 주입 프롬프트
   (첨부 펜스)가 대화로 노출되고 질문이 밀리는지. 재현 성공 = 노출 단언이 참. */
import fs from 'node:fs'
import crypto from 'node:crypto'
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
const NONCE = crypto.randomBytes(3).toString('hex')
const QMARK = `R424재현마커-${NONCE} — 첨부의 숫자 두 개를 더하면? 계산 과정을 생각한 뒤 답해줘.`
const TMP = `${OUT}/r424-note.txt`
fs.writeFileSync(TMP, `재현 문서(${NONCE}): 첫째 숫자는 214, 둘째 숫자는 377 이다.`)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const login = async () => {
  await page.goto(URL, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1500)
  if (await page.getByText('my-agents 로그인', { exact: true }).isVisible().catch(() => false)) {
    await page.getByPlaceholder('you@example.com').fill(_fx.email)
    await page.getByPlaceholder('비밀번호').fill(_fx.password)
    await page.getByRole('button', { name: '로그인' }).click(); await page.waitForTimeout(1500)
  }
}
const gotoPg = async () => {
  await page.getByText('Playground', { exact: true }).first().click(); await page.waitForTimeout(1500)
  if ((await page.locator('button').filter({ hasText: 'personal-secretary' }).count()) > 0) return
  await page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first().click()
  await page.getByText('personal-secretary', { exact: false }).first().click(); await page.waitForTimeout(1000)
}
try {
  await login(); await gotoPg()
  // thinking 켬(오버라이드 2단계)
  await page.getByText('오버라이드', { exact: false }).first().click(); await page.waitForTimeout(800)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(600)
  await page.getByText('Thinking 모드', { exact: true }).locator('xpath=following::div[contains(@class,"ant-select")][1]').click()
  await page.waitForTimeout(400)
  await page.getByRole('option', { name: /^켬$/ }).click().catch(async () => {
    await page.locator('.ant-select-dropdown:visible').getByText(/^켬$/).first().click()
  })
  await page.getByRole('button', { name: /적용/ }).click(); await page.waitForTimeout(1000)
  // 첨부 + 질문
  await page.locator('input[type="file"]').setInputFiles(TMP)
  await page.getByText('r424-note.txt', { exact: false }).waitFor({ timeout: 10000 })
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill(QMARK); await input.press('Enter')
  await page.getByText('사고 과정', { exact: false }).first().waitFor({ timeout: 120000 })
  ok(true, '준비: 첨부+thinking 턴 생성(사고 패널 라이브)')
  await page.waitForTimeout(10000)
  // 재로드 → 세션 재선택
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1500)
  await login(); await gotoPg()
  await page.locator('button').filter({ hasText: /세션|sess-/ }).first().click(); await page.waitForTimeout(800)
  await page.getByText(new RegExp(NONCE)).first().click({ timeout: 8000 }).catch(async () => {
    await page.getByText(/참고용|1턴/).first().click({ timeout: 8000 })
  })
  await page.waitForTimeout(2000)
  const body = await page.locator('body').innerText()
  ok(body.includes('⟦첨부') || body.includes('참고용 **데이터**'), '재현① 내부 주입 프롬프트(펜스)가 대화로 노출')
  const idxFence = body.indexOf('참고용')
  const idxQ = body.indexOf(`R424재현마커-${NONCE}`)
  ok(idxFence >= 0 && idxQ > idxFence, '재현② 질문이 주입 본문 아래로 밀림(순서)')
  await page.screenshot({ path: `${OUT}/r424-bug-repro.png` })
  console.log(fails.length ? `\nNOT-REPRODUCED ${fails.length}` : '\nREPRODUCED')
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: `${OUT}/r424-debug.png` }).catch(() => {})
} finally { await browser.close() }
