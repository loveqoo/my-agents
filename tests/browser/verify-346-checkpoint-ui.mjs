/* verify_346 UI — 체크포인트 스윕 노브 + 만료 승인 표기(스펙 346).

   memory `ui-verification-must-be-functional`: 렌더 확인만으론 기능이 깨진 채 통과한다.
   그래서 **실제 동작을 시키고 효과를 단언**한다:
     U1 배치 > 체크포인트 탭: TTL(24시간)·cron이 서버 값으로 채워져 있다(설정이 실제로 로드됨).
     U2 Dry-run을 **눌러서** 실행 → 결과 토스트 + 실행 이력에 checkpoint-cleanup 행이 생긴다(왕복).
     U3 승인 > 처리됨: status='expired' 행이 **'만료'**로 뜬다 — 빨간 '거부'로 뜨면 실패
        (사람이 거부한 것처럼 거짓말하는 화면. 만료는 배치가 남긴 상태지 사람의 결정이 아니다).
   실행: node tests/browser/verify-346-checkpoint-ui.mjs
   전제: expired 승인 1건이 DB에 심겨 있어야 한다(러너가 심고 지운다).
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

// ---- 배치 > 체크포인트 탭
await page.locator('a, li, span', { hasText: /^배치$/ }).first().click().catch(() => {})
await page.waitForTimeout(2000)
await page.locator('.ant-tabs-tab', { hasText: '체크포인트' }).first().click()
await page.waitForTimeout(1200)

const panelText = await page.locator('.ant-tabs + div, main').first().innerText()
const ttlVal = await page.locator('input.ant-input-number-input').first().inputValue().catch(() => '')
const cronVal = await page.locator('input[placeholder*="0 * * * *"]').first().inputValue().catch(() => '')
check(ttlVal === '24', `U1a TTL이 서버 값(24)으로 로드됨 (got "${ttlVal}")`)
check(cronVal.trim().length > 0, `U1b cron이 서버 값으로 로드됨 (got "${cronVal}")`)
check(/checkpoint-cleanup/.test(panelText), 'U1c 잡 식별자(checkpoint-cleanup) 표기')

// ---- Dry-run 실행(실제 클릭 → 왕복)
await page.locator('button', { hasText: 'Dry-run' }).first().click()
await page.waitForTimeout(2500)
const toast = await page.locator('.ant-message').innerText().catch(() => '')
check(/dry-run 완료/i.test(toast), `U2a Dry-run 토스트(실행 왕복) (got "${toast.replace(/\s+/g, ' ').slice(0, 60)}")`)

const runsText = await page.locator('table').last().innerText().catch(() => '')
check(/checkpoint-cleanup/.test(runsText) && /dry-run/i.test(runsText),
  'U2b 실행 이력에 checkpoint-cleanup(dry-run) 행이 남음')

// ---- 승인 > 처리됨: 만료 표기
await page.locator('a, li, span', { hasText: /^승인$/ }).first().click().catch(() => {})
await page.waitForTimeout(2000)
await page.locator('.ant-tabs-tab', { hasText: /처리/ }).first().click()
await page.waitForTimeout(2000)

const row = page.locator('tr', { hasText: 'v346-expired' }).first()
await row.waitFor({ timeout: 10000 }).catch(() => {})
const rowText = await row.innerText().catch(() => '')
check(/만료/.test(rowText), `U3a 만료 승인이 '만료'로 표시 (row="${rowText.replace(/\s+/g, ' ').slice(0, 70)}")`)
check(!/거부/.test(rowText), 'U3b 만료가 **거부로 표시되지 않음**(사람의 결정이 아님 — 화면이 거짓말하지 않는다)')

await browser.close()
console.log()
if (fails.length) {
  console.log(`FAIL ${fails.length}건: ${JSON.stringify(fails)}`)
  process.exit(1)
}
console.log(`VERIFY346_UI_OK — ${passed}건 전부 통과`)
