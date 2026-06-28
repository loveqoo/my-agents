/* RAG 샘플 적재 검증 스크린샷 (스펙 048 #9) — 시스템 Chrome.
   admin(vite :5173) 로그인 후 RAG 컬렉션 탭에서:
   (1) docs_kb가 populated(상태 준비됨 + 문서 4 + 청크 4)로 보이는지 — #9의 핵심 산출물.
   (2) 문서 관리 Drawer에서 4개 샘플 문서가 ready로 적재됐는지.
   를 캡처. 게이트 배너(임베딩 모델 0개)는 라이브에 임베딩 모델이 존재해 표시되지 않으므로
   타입체크+코드 로직으로 검증(파괴적으로 모델을 지우지 않는다).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-collections-048.mjs /tmp/coll048 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/coll048'
// self-fixture(스펙 050 Phase 3): ADMIN_EMAIL 미지정이면 던짐용 super 즉석 시드 → 종료 시 자동 삭제.
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 960 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // (1) RAG 컬렉션 목록 — docs_kb가 populated로 보여야
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-list-populated.png`, fullPage: true })
  const bodyText = await page.locator('body').innerText().catch(() => '')
  const hasDocsKb = /docs_kb/.test(bodyText)
  const hasReady = /준비됨/.test(bodyText)
  log('STEP1_LIST docs_kb=' + hasDocsKb + ' ready=' + hasReady)

  // (2) docs_kb 문서 Drawer — 4개 샘플이 완료(ready)로
  const row = page.locator('table tbody tr').filter({ hasText: 'docs_kb' }).first()
  if (await row.count()) {
    await row.getByRole('button', { name: /문서/ }).first().click()
    await page.waitForTimeout(1000)
    await page.screenshot({ path: `${OUT}-2-docs-drawer.png`, fullPage: true })
    const drawerText = await page.locator('.ant-drawer').innerText().catch(() => '')
    const docRows = (drawerText.match(/\.md/g) || []).length
    const doneCount = (drawerText.match(/완료/g) || []).length
    log('STEP2_DRAWER mdDocs=' + docRows + ' done=' + doneCount)
  } else {
    log('STEP2_DRAWER docs_kb row not found')
  }

  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
