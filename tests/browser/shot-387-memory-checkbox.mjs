/* 스펙 387 후속 — 장기 기억 컨트롤: 단일 블록이면 체크박스.
   단언: (1) 새 에이전트 폼에 "장기 기억 (mem0) 사용" 체크박스 노출(구 다중 Select 부재)
   (2) 토글 동작(끔→켬→끔) (3) 기존 personal-secretary 편집 폼에선 체크됨(저장값 반영).
   실행: PLAYWRIGHT_DIR=$PWD/tests/e2e/node_modules/playwright node tests/browser/shot-387-memory-checkbox.mjs */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { provisionSuper } from './_fixture.mjs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'out-387')
const BASE = process.env.ADMIN_URL || 'http://127.0.0.1:5173'
const { email, password } = provisionSuper()

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
let fails = 0
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
  if (!ok) fails++
}

await page.goto(BASE + '/')
await page.getByPlaceholder('you@example.com').fill(email)
await page.getByPlaceholder('비밀번호').fill(password)
await page.getByRole('button', { name: /로그인|login/i }).click()
await page.waitForTimeout(1500)

await page.locator('[data-menu-id$="agents"]').first().click({ timeout: 5000 })
await page.waitForTimeout(1100)

// 1) 새 에이전트 폼 — 체크박스 존재·토글
await page.getByRole('button', { name: /새 에이전트|에이전트 만들|추가|생성/ }).first().click({ timeout: 5000 })
await page.waitForTimeout(900)
// 4단계 Steps 모달 — 기억 필드는 3단계 "세부". 1·2단계 최소 입력 후 전진.
await page.getByPlaceholder(/research-assistant/).fill('v387-ui-probe')
await page.getByRole('button', { name: '다음' }).click()
await page.waitForTimeout(700)
await page.screenshot({ path: path.join(OUT, 'step2.png'), fullPage: false })
const cb = page.getByRole('checkbox', { name: /장기 기억.*사용/ }).first()
const cbVisible = await cb.isVisible().catch(() => false)
check('새 폼: 장기 기억 체크박스 노출', cbVisible)
const oldSelect = await page.getByText('mem0 장기 기억에서 회상').isVisible().catch(() => false)
check('새 폼: 구 다중 Select 부재', !oldSelect)
if (cbVisible) {
  check('새 폼: 초기 미체크', !(await cb.isChecked()))
  await cb.click()
  check('토글 켬', await cb.isChecked())
  await page.screenshot({ path: path.join(OUT, 'form-checked.png'), fullPage: false })
  await cb.click()
  check('토글 끔', !(await cb.isChecked()))
}
await page.setViewportSize({ width: 400, height: 850 }) // 좁은 해상도 깨짐 확인
await page.waitForTimeout(400)
await page.screenshot({ path: path.join(OUT, 'form-narrow.png'), fullPage: false })
await page.setViewportSize({ width: 1280, height: 900 })
await page.keyboard.press('Escape')
await page.waitForTimeout(600)

// 2) 기존 에이전트(personal-secretary) 편집 — 저장값(장기 기억 켬) 반영
await page.locator('[data-menu-id$="agents"]').first().click({ timeout: 5000 })
await page.waitForTimeout(900)
await page.getByText('personal-secretary', { exact: false }).first().click({ timeout: 5000 })
await page.waitForTimeout(1100)
await page.getByRole('button', { name: /편집|수정/ }).first().click({ timeout: 5000 })
await page.waitForTimeout(900)
await page.getByRole('button', { name: '다음' }).click().catch(() => {})
await page.waitForTimeout(600)
const cb2 = page.getByRole('checkbox', { name: /장기 기억.*사용/ }).first()
const cb2Visible = await cb2.isVisible().catch(() => false)
check('편집 폼: 체크박스 노출', cb2Visible)
if (cb2Visible) check('편집 폼: 저장값 반영(체크됨)', await cb2.isChecked())
await page.screenshot({ path: path.join(OUT, 'edit-checked.png'), fullPage: false })

await browser.close()
console.log(fails === 0 ? 'SHOT387_OK' : `SHOT387_FAIL (${fails})`)
process.exit(fails === 0 ? 0 : 1)
