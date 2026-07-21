/* 스펙 422 공식 문서(docs/user-guide.md)용 전 메뉴 스크린샷.
   실행: PLAYWRIGHT_DIR=$(pwd)/tests/e2e/node_modules/playwright node tests/browser/shot-422-docs-menus.mjs
   산출: docs/images/menu-*.png (유저 가이드가 참조 — UI 바뀌면 재실행해 갱신) */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'docs/images'
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
const closeOverlays = async () => {
  for (let i = 0; i < 5; i++) {
    const close = page.locator('.ant-drawer-close, .ant-modal-close').first()
    if (!(await close.count())) break
    await close.click().catch(() => {})
    await page.waitForTimeout(400)
  }
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await shot('login')
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await nav('개요'); await shot('menu-overview')
  await nav('에이전트'); await shot('menu-agents')
  const newBtn = page.getByRole('button', { name: '새 에이전트' }).first()
  if (await newBtn.count()) {
    await newBtn.click(); await page.waitForTimeout(800)
    await shot('menu-agent-form')
    await closeOverlays()
  }
  await nav('빌딩 블록'); await shot('menu-blocks')
  await nav('승인'); await shot('menu-approvals')
  await nav('노드'); await shot('menu-node-library')
  await nav('RAG 컬렉션'); await shot('menu-collections')
  await nav('세션'); await shot('menu-sessions')
  await nav('메모리'); await shot('menu-memory')
  await nav('프로바이더·모델'); await shot('menu-models')
  await nav('유저'); await shot('menu-users')
  await nav('배치'); await shot('menu-batch')
  await nav('허용 호스트'); await shot('menu-allowed-hosts')
  await nav('설정'); await shot('menu-settings')
  await nav('Playground'); await shot('menu-playground')
  await nav('평가'); await shot('menu-eval')
  console.log('\nDONE')
} catch (e) {
  console.log('EXCEPTION:', String(e))
  process.exitCode = 1
} finally {
  await browser.close()
}
