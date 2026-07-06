/* 노코드 가이드(docs/guide/nocode-agent-guide.md)용 메뉴별 스크린샷 캡처.
   실행: PLAYWRIGHT_DIR=$(pwd)/tests/e2e/node_modules/playwright node tests/browser/shot-guide-menus.mjs
   산출: docs/guide/images/guide-*.png (가이드가 참조 — UI 바뀌면 재실행해 갱신) */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'docs/guide/images'
import { mkdirSync } from 'node:fs'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()

const shot = async (name) => {
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${OUT}/${name}.png` })
  console.log('SHOT', name)
}
const nav = async (label) => {
  await page.getByText(label, { exact: true }).first().click()
  await page.waitForTimeout(700)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await nav('개요'); await shot('guide-overview')
  await nav('에이전트'); await shot('guide-agents')
  // 에이전트 생성 폼(권한 붙이기가 보이는 화면)
  const newBtn = page.getByRole('button', { name: '새 에이전트' }).first()
  if (await newBtn.count()) {
    await newBtn.click(); await page.waitForTimeout(800)
    await shot('guide-agent-form')
    // 포커스 무관 닫기(회고 172): 닫기 버튼 클릭 루프
    for (let i = 0; i < 5; i++) {
      const close = page.locator('.ant-drawer-close, .ant-modal-close').first()
      if (!(await close.count())) break
      await close.click().catch(() => {})
      await page.waitForTimeout(400)
    }
  }
  await nav('빌딩 블록'); await shot('guide-blocks')
  await nav('RAG 컬렉션'); await shot('guide-collections')
  await nav('승인'); await shot('guide-approvals')
  await nav('프로바이더·모델'); await shot('guide-models')
  await nav('Playground'); await shot('guide-playground')
  await nav('평가'); await shot('guide-eval')
  console.log('\nDONE')
} catch (e) {
  console.log('EXCEPTION:', String(e))
  process.exitCode = 1
} finally {
  await browser.close()
}
