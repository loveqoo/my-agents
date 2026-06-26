/* Playground 화면 검증용 스크린샷 — 시스템 Chrome(channel:'chrome')로 구동해
   브라우저 다운로드 없이 동작. admin(vite :5173)을 띄우고 에이전트 picker를 열어
   모델 배지를 캡처한다.

   실행: NODE_PATH=<npx-playwright>/node_modules node tests/browser/shot-playground.mjs [out.png]
   (npx 캐시 경로는 호출 측에서 NODE_PATH로 주입 — package.json 오염 없이 재사용.)

   왜 이렇게: 라우팅이 URL이 아니라 React state라 딥링크 불가 → 메뉴 'Playground'를
   클릭해 진입한 뒤, 헤더의 AgentCombo 버튼을 눌러 드롭다운을 펼친다.

   playwright는 ESM이 NODE_PATH를 안 보므로 PLAYWRIGHT_DIR(절대경로)로 동적 import. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/playground-shot.png'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 900, height: 1200 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  // 메뉴 'Playground' 클릭(도구 그룹에 바로 노출).
  await page.getByText('Playground', { exact: true }).first().click()
  // 에이전트가 로드돼 헤더 AgentCombo 버튼이 뜰 때까지 — 모델 배지 텍스트로 대기.
  await page.waitForTimeout(1500)
  // 헤더의 picker 버튼(에이전트 이름 + 모델 배지)을 눌러 드롭다운 펼치기.
  // AgentCombo 버튼은 헤더 첫 번째 <button> (avatar+name+model). persona/이름으로 찾는다.
  const combo = page.locator('button').filter({ hasText: '코드 정의' }).first()
  await combo.click().catch(() => {})
  await page.waitForTimeout(600)
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT_OK', OUT)
  if (errors.length) console.log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 5)))
} catch (e) {
  console.log('SHOT_FAIL', e.message)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
} finally {
  await browser.close()
}
