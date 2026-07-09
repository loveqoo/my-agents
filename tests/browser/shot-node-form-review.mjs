/* 노드형 폼 UI/UX 검토용 상태별 캡처 (스펙 259-262 리뷰) — 시스템 Chrome.
   상태 트리: ①정체성(노드형 선택) ②하는 일 빈 상태 ③노드 2개+JSON 펼침+clean ④요약 ⑤모바일(360px) ③.
   판정은 사람이(스크린샷 육안) — 이 스크립트는 상태 도달+캡처만.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-node-form-review.mjs tests/browser/out-review */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/node-form-review'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const log = (...a) => console.log(...a)

async function login(page) {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)
}

async function toNodeType(page) {
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill('review-probe')
  const field = page.locator('label', { hasText: '에이전트 종류' }).first()
  await field.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
}

async function fillNodes(page) {
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(300)
  const boxes = page.getByPlaceholder('이 노드가 할 일을 지시하세요 (예: 입력을 분석해 핵심 3가지를 뽑아라)')
  await boxes.first().fill('입력을 분석해 핵심 3가지를 뽑아라')
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(300)
  await boxes.nth(1).fill('요약해서 한 문단으로 정리하라')
  // 노드2: 깨끗이 받기 + JSON(필수 키 입력 펼침)
  await page.getByText('깨끗이 받기', { exact: true }).last().click({ force: true })
  await page.waitForTimeout(200)
  await page.getByText('JSON', { exact: true }).last().click({ force: true })
  await page.waitForTimeout(300)
}

try {
  // ── 데스크톱 1280 ──
  const ctx1 = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
  const p1 = await ctx1.newPage()
  await login(p1)
  await toNodeType(p1)
  await p1.screenshot({ path: `${OUT}-1-identity.png` })          // ① 정체성(노드형)
  await p1.getByRole('button', { name: '다음' }).click()
  await p1.waitForTimeout(500)
  await p1.screenshot({ path: `${OUT}-2-empty.png` })              // ② 하는 일 빈 상태
  await p1.getByRole('button', { name: /노드 추가/ }).click()
  await p1.waitForTimeout(300)
  const boxes = p1.getByPlaceholder('이 노드가 할 일을 지시하세요 (예: 입력을 분석해 핵심 3가지를 뽑아라)')
  await boxes.first().fill('입력을 분석해 핵심 3가지를 뽑아라')
  await p1.getByRole('button', { name: /노드 추가/ }).click()
  await p1.waitForTimeout(300)
  await boxes.nth(1).fill('요약해서 한 문단으로 정리하라')
  await p1.getByText('깨끗이 받기', { exact: true }).last().click({ force: true })
  await p1.waitForTimeout(200)
  await p1.getByText('JSON', { exact: true }).last().click({ force: true })
  await p1.waitForTimeout(300)
  await p1.screenshot({ path: `${OUT}-3-filled.png`, fullPage: false }) // ③ 노드 2개(뷰포트)
  // 모달 내부 전체(스크롤 포함) 캡처: 모달 요소만
  const modal = p1.locator('.ant-modal-container').first()
  await modal.screenshot({ path: `${OUT}-3-filled-modal.png` }).catch(() => {})
  await p1.getByRole('button', { name: '다음' }).click()
  await p1.waitForTimeout(400)
  await p1.getByRole('button', { name: '다음' }).click()
  await p1.waitForTimeout(400)
  await p1.locator('.ant-modal-container').first().screenshot({ path: `${OUT}-4-summary.png` }).catch(() => {})
  await ctx1.close()
  log('desktop captured')

  // ── 모바일 360 ──
  const ctx2 = await browser.newContext({ viewport: { width: 360, height: 780 } })
  const p2 = await ctx2.newPage()
  await login(p2)
  await toNodeType(p2)
  await fillNodes(p2)
  await p2.screenshot({ path: `${OUT}-5-mobile.png`, fullPage: false }) // ⑤ 모바일 노드 카드
  // 가로 오버플로 수치 측정(ui-audit 축2 방식)
  const overflow = await p2.evaluate(() => {
    const doc = document.documentElement
    const modal = document.querySelector('.ant-modal-container')
    return {
      docScrollX: doc.scrollWidth - doc.clientWidth,
      modalScrollX: modal ? modal.scrollWidth - modal.clientWidth : null,
    }
  })
  log('MOBILE_OVERFLOW=' + JSON.stringify(overflow))
  await ctx2.close()
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
