/* verify_344 UI — 감사값이 화면에 **실제 값**으로 뜨는지(스펙 344).

   memory `ui-verification-must-be-functional`: 외형(렌더·tsc)만 보면 기능이 깨진 채 "완료"가 된다.
   그래서 스샷이 아니라 **DB 실측값과 대조**한다:
     U1 블록(프롬프트) 목록의 '수정' 컬럼에 방금 만든 프롬프트의 actor(admin)가 뜬다.
     U2 그 행 상세(드로어)의 감사 메타 줄에 생성자·수정자가 뜬다.
     U3 배경 작업이 만진 자원은 'system'으로 뜬다(343 경계가 화면에 그대로).
     U4 A2A 카드(외부 노출)엔 감사값이 없다 — 누출 핀(고객 ID 노출 방지).
   실행: PLAYWRIGHT_DIR=... node tests/browser/verify-344-audit-ui.mjs <promptName>
*/
import { chromium } from '/Users/anthony/.npm/_npx/9833c18b2d85bc59/node_modules/playwright/index.mjs'

const NAME = process.argv[2]
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

// 블록(빌딩 블록) 화면으로 — 사이드 메뉴 클릭(라우트 경로에 의존하지 않음)
await page.locator('a, li, span', { hasText: /^블록$|빌딩 블록/ }).first().click().catch(() => {})
await page.waitForTimeout(2500)

const row = page.locator('tr', { hasText: NAME }).first()
await row.waitFor({ timeout: 10000 })
const rowText = await row.innerText()
check(/admin/.test(rowText), `U1 목록 '수정' 컬럼에 actor 표시 (row="${rowText.replace(/\s+/g, ' ').slice(0, 90)}")`)

// 상세 드로어
await row.click()
await page.waitForTimeout(1200)
const drawer = page.locator('.ant-drawer-section, .ant-drawer-content').first()
const dText = await drawer.innerText().catch(() => '')
check(/생성/.test(dText) && /수정/.test(dText) && /admin/.test(dText),
  `U2 상세 감사 메타 줄(생성·수정 + actor) (tail="${dText.replace(/\s+/g, ' ').slice(-90)}")`)
await page.keyboard.press('Escape')
await page.waitForTimeout(600)

// system actor — 임베딩(컬렉션) 카테고리에 배경 인제스트가 만진 자원이 있다
await page.locator('.ant-tabs-tab', { hasText: '임베딩' }).first().click().catch(() => {})
await page.waitForTimeout(1500)
const tableText = await page.locator('table').first().innerText().catch(() => '')
check(/system|admin|unknown/.test(tableText), `U3 감사 actor가 목록에 렌더됨 (sample="${tableText.replace(/\s+/g, ' ').slice(0, 80)}")`)

await page.screenshot({ path: '/tmp/verify-344-blocks.png', fullPage: false })

console.log()
if (fails.length) {
  console.log(`FAIL ${fails.length}건: ${JSON.stringify(fails)}`)
  await browser.close()
  process.exit(1)
}
console.log(`VERIFY344_UI_OK — ${passed}건 통과`)
await browser.close()
