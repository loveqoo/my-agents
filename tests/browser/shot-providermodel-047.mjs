/* 스펙 047 검증 스크린샷 — 프로바이더·모델 통합 뷰(마스터-디테일) 시각 + 텍스트 단언.
   admin(vite :5173) 로그인 후:
   (1) 사이드 메뉴가 '프로바이더·모델' 하나로 합쳐짐(이전 '프로바이더'+'모델' 두 항목 → 하나).
   (2) 통합 뷰: 좌측 마스터에 프로바이더 + kind 배지(Local/Mock)·설명. 우측 디테일.
   (3) [GET /models] → 실모델 나열, 등록된 mock-chat 체크박스 ON, 카탈로그 칩/미수록 표시.
   데이터는 라이브 백엔드(listProviders/available-models)에서 온다.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-providermodel-047.mjs /tmp/pm047 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/pm047'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }
const present = async (name) => (await page.getByText(name, { exact: true }).count()) > 0

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1360, height: 1000 } })
const page = await ctx.newPage()

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // (1) 메뉴 통합 — '프로바이더·모델' 단일 항목, 옛 분리 항목 부재.
  const merged = page.getByRole('menuitem', { name: '프로바이더·모델' })
  ok((await merged.count()) > 0, "메뉴: '프로바이더·모델' 단일 항목 존재")
  ok((await page.getByRole('menuitem', { name: '프로바이더', exact: true }).count()) === 0,
     "메뉴: 옛 '프로바이더' 단독 항목 부재(통합됨)")
  ok((await page.getByRole('menuitem', { name: '모델', exact: true }).count()) === 0,
     "메뉴: 옛 '모델' 단독 항목 부재(통합됨)")

  // (2) 통합 뷰 진입 — 마스터-디테일 + kind 배지·설명.
  await merged.click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-master-detail.png`, fullPage: true })
  ok(await present('Local'), 'kind 배지: Local 표시(#6)')
  ok(await present('Mock'), 'kind 배지: Mock 표시(#6)')
  ok(await present('실제 로컬 MLX 서버'), '프로바이더 설명 표시(#6)')

  // (3) 디테일에서 GET /models — 실모델 토글 목록.
  // 마스터에서 mock 프로바이더(127.0.0.1:8000) 선택 → 디테일에 mock-chat 등록 체크.
  await page.getByText('127.0.0.1:8000', { exact: true }).first().click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /GET \/models/ }).click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}-2-models-toggle.png`, fullPage: true })
  ok(await present('mock-chat'), '실모델: mock-chat 행 표시(GET /models)')
  // 등록된 모델 체크박스가 ON(antd Checkbox checked)
  const checkedBoxes = await page.locator('.ant-checkbox-checked').count()
  ok(checkedBoxes >= 1, `등록 모델 체크박스 ON(checked=${checkedBoxes})`)
  ok(await present('등록됨') || (await page.getByText(/등록됨/).count()) > 0, "등록 배지 '등록됨' 표시")

  console.log('')
  if (fails.length) { console.log(`검증 실패 ${fails.length}건`); process.exitCode = 1 }
  else console.log('스펙 047 브라우저 검증 — 전부 통과.')
} catch (e) {
  console.error('SHOT ERROR:', e.message)
  process.exitCode = 2
} finally {
  await browser.close()
}
