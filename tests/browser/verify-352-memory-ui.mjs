/* verify_352 UI — 기억 정리 · 실행 이력 탭 (스펙 351·352).

   memory `ui-verification-must-be-functional`: 렌더 확인만으론 기능이 깨진 채 통과한다.
   그래서 **실제로 누르고 효과를 단언**한다(스샷 한 장으로 완료 선언 금지):
     U1 배치 > 기억 정리 탭: 유예(7일)·cron이 **서버 값으로** 채워져 있다(설정이 실제로 로드됨).
     U2 Dry-run을 **눌러서** 실행 → 토스트 + 실행 이력에 memory-cleanup(dry-run) 행이 생긴다(왕복).
     U3 배치 > 실행 이력 탭도 같은 왕복(스펙 351 — api.ts에 필드가 빠져 있던 곳).
   실행: node tests/browser/verify-352-memory-ui.mjs   (api 8000 + vite 5173 필요)
*/
import { chromium } from '/Users/anthony/.npm/_npx/9833c18b2d85bc59/node_modules/playwright/index.mjs'

const BASE = 'http://127.0.0.1:5173'
const fails = []
let passed = 0
const check = (cond, msg) => {
  console.log((cond ? '  ok  ' : ' FAIL ') + msg)
  cond ? passed++ : fails.push(msg)
}

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })

await page.goto(BASE)
await page.fill('input#email', 'admin@example.com')
await page.fill('input#password', 'adminpass123')
await page.locator('button', { hasText: '로그인' }).first().click()
await page.waitForTimeout(3000)

await page.locator('a, li, span', { hasText: /^배치$/ }).first().click().catch(() => {})
await page.waitForTimeout(2000)

// ---- U1/U2 기억 정리 탭
await page.locator('.ant-tabs-tab', { hasText: '기억' }).first().click()
await page.waitForTimeout(1200)

const panelText = await page.locator('main').first().innerText()
const grace = await page.locator('input.ant-input-number-input').first().inputValue().catch(() => '')
check(grace === '7', `U1a 유예가 서버 값(7일)으로 로드됨 (got "${grace}")`)
check(/memory-cleanup/.test(panelText), 'U1b 잡 식별자(memory-cleanup) 표기')

await page.locator('button', { hasText: 'Dry-run' }).first().click()
await page.waitForTimeout(2500)
const toast = await page.locator('.ant-message').innerText().catch(() => '')
check(/dry-run/i.test(toast), `U2a Dry-run 토스트(실행 왕복) (got "${toast.replace(/\s+/g, ' ').slice(0, 60)}")`)

const runsText = await page.locator('table').last().innerText().catch(() => '')
check(
  /memory-cleanup/.test(runsText),
  'U2b 실행 이력에 memory-cleanup 행이 남음(화면 → API → DB 왕복)',
)

// ---- U3 실행 이력 탭(스펙 351)
await page.locator('.ant-tabs-tab', { hasText: /실행 이력|이력/ }).first().click()
await page.waitForTimeout(1200)
const hText = await page.locator('main').first().innerText()
const hDays = await page.locator('input.ant-input-number-input').first().inputValue().catch(() => '')
check(hDays === '90', `U3a 보존기간이 서버 값(90일)으로 로드됨 (got "${hDays}")`)
check(/history-cleanup/.test(hText), 'U3b 잡 식별자(history-cleanup) 표기')

await page.screenshot({ path: 'tests/browser/out-352-memory-tab.png' })
await browser.close()
console.log()
if (fails.length) {
  console.log(`FAIL ${fails.length}건: ${JSON.stringify(fails)}`)
  process.exit(1)
}
console.log(`VERIFY352_UI_OK — ${passed}건 전부 통과`)
