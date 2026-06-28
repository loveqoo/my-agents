/* RAG 컬렉션 뷰 검증 스크린샷 (스펙 036) — 시스템 Chrome.
   admin(vite :5173) 로그인 후:
   (1) RAG 컬렉션 탭 목록(시드 4개 + 임베딩 모델/차원/문서/청크/상태 컬럼)
   (2) 컬렉션 생성 모달(이름/설명/임베딩 모델 드롭다운/chunk_size/chunk_overlap)
   (3) 임베딩 모델 드롭다운 옵션 노출(생성 가능 여부)
   (4) 문서 관리 Drawer(업로드 컨트롤 + 문서 목록/상태)
   (5) BlocksView embedding 카테고리가 사라졌는지(깨진 vector-tables CRUD 제거 확인)
   를 캡처. 읽기 위주 — 실제 생성은 verify036_ prefix로 만들고 끝에 삭제.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-collections-036.mjs /tmp/coll036 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/coll036'
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

  // (1) RAG 컬렉션 탭
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}-1-collections-list.png`, fullPage: true })
  const rows = await page.locator('table tbody tr').count()
  const headerText = await page.locator('table thead').first().innerText().catch(() => '')
  log('STEP1_LIST rows=' + rows + ' header=' + JSON.stringify(headerText.replace(/\s+/g, ' ').trim()))

  // (2) 컬렉션 생성 모달
  const createBtn = page.getByRole('button', { name: /컬렉션 (생성|만들기|추가|등록)/ }).first()
  await createBtn.click()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}-2-create-modal.png`, fullPage: true })

  // (3) 임베딩 모델 드롭다운 옵션 — Select 열어서 옵션 개수 확인
  const sel = page.locator('.ant-select-selector').first()
  let optCount = 0
  if (await sel.count()) {
    await sel.click()
    await page.waitForTimeout(500)
    optCount = await page.locator('.ant-select-item-option').count()
    await page.screenshot({ path: `${OUT}-3-model-dropdown.png`, fullPage: true })
    await page.keyboard.press('Escape')
  }
  log('STEP3_MODEL_DROPDOWN options=' + optCount)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // (4) 문서 관리 Drawer — 첫 컬렉션 행의 관리/문서 액션
  const manageBtn = page.getByRole('button', { name: /문서|관리/ }).first()
  if (await manageBtn.count()) {
    await manageBtn.click()
    await page.waitForTimeout(900)
    await page.screenshot({ path: `${OUT}-4-document-drawer.png`, fullPage: true })
    const hasUpload = await page.locator('.ant-upload').count()
    log('STEP4_DRAWER uploadControl=' + hasUpload)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(400)
  } else {
    log('STEP4_DRAWER manageBtn=0 (no rows?)')
  }

  // (5) BlocksView embedding 카테고리 제거 확인 — 빌딩 블록 탭에서 'RAG 컬렉션'/'임베딩' 카테고리가 없어야
  await page.getByText('빌딩 블록', { exact: true }).first().click().catch(() => {})
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-5-blocks-no-embedding.png`, fullPage: true })
  const blocksText = await page.locator('body').innerText().catch(() => '')
  const hasVectorCat = /vector-tables/.test(blocksText)
  log('STEP5_BLOCKS leaksVectorTables=' + hasVectorCat)

  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
