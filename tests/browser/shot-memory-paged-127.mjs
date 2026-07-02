/* 스펙 127 검증 — 메모리 탭 상단 Segmented [일치 검색|유사도 검색] 토글.
   일치 모드 = 서버 페이지네이션 목록(검색 Input + "전체 N건 · 스코프 …" 총계 줄 + DataTable +
   20건 초과 시 Pagination). 유사도 모드 = 기존 회상 시험 패널(질의 textarea + 조회 버튼 + 진단
   Collapse). 시스템 Chrome. 사전에 user_id='verify127-e2e'로 mem0_memories 25건 + sessions 1건을
   시드해둬야 드롭다운에 노출된다(list_memory_users는 sessions.user_id distinct가 출처).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-memory-paged-127.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/memory-paged-127.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.getByText('유저 메모리', { exact: true }).first().click()
  await page.waitForTimeout(600)

  // 1) 콤보박스 클릭 → verify127-e2e 옵션 클릭(미등록 유저로 노출됨).
  const combo = page.getByRole('combobox').first()
  await combo.click({ timeout: 8000 })
  await page.waitForTimeout(500)
  const opt = page.locator('.ant-select-item-option').filter({ hasText: 'verify127-e2e' }).first()
  const optFound = await opt.count().then((n) => n > 0).catch(() => false)
  check(optFound, '드롭다운에 verify127-e2e 옵션 노출')
  if (optFound) {
    await opt.click({ timeout: 8000 })
  } else {
    await page.keyboard.press('Escape')
  }
  await page.waitForTimeout(800)

  // 2) Segmented [일치 검색|유사도 검색] 존재.
  const segmented = page.locator('.ant-segmented').first()
  check(await segmented.isVisible().catch(() => false), 'Segmented [일치 검색|유사도 검색] 존재')

  // 3) 일치 모드 기본: "전체 25건" 표시.
  await page.waitForTimeout(800)
  const bodyText1 = await page.locator('#root').innerText().catch(() => '')
  check(bodyText1.includes('전체 25건'), '일치 모드 기본 총계 "전체 25건" 표시')

  // 4) Pagination 존재, 2페이지 클릭 → 행 수 5.
  const pagination = page.locator('.ant-pagination').first()
  const paginationVisible = await pagination.isVisible().catch(() => false)
  check(paginationVisible, 'Pagination(.ant-pagination) 존재')
  if (paginationVisible) {
    await page.locator('.ant-pagination-item-2').click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(800)
    const rowCount = await page.locator('tbody tr').count().catch(() => 0)
    check(rowCount === 5, `2페이지 행 수 5(실측 ${rowCount})`)
  } else {
    check(false, '2페이지 행 수 5 (Pagination 없어 스킵)')
  }

  // 5) 검색 Input에 "기억 #7" 입력 → 디바운스 대기 → "1건" 표시.
  const searchInput = page.getByPlaceholder('기억 본문 부분일치 검색 (전체 대상)')
  await searchInput.fill('기억 #7')
  await page.waitForTimeout(1500)
  const bodyText2 = await page.locator('#root').innerText().catch(() => '')
  // \b는 한글(비-\w)과 붙으면 경계로 안 잡힐 수 있어(예: "1건"의 '건' 뒤) 정확한 총계 문구로 매칭.
  check(/일치 1건/.test(bodyText2), '검색 "기억 #7" → "일치 1건" 표시')

  // 6) Segmented "유사도 검색" 클릭 → 회상 시험 textarea 표시.
  await page.getByText('유사도 검색', { exact: true }).click({ timeout: 8000 })
  await page.waitForTimeout(600)
  const textarea = page.locator('textarea').first()
  check(await textarea.isVisible().catch(() => false), '유사도 검색 모드에서 회상 시험 textarea 표시')

  // 7) 비밀(sk-...) 미노출.
  const bodyText3 = await page.locator('#root').innerText().catch(() => '')
  check(!/sk-[A-Za-z0-9]{6,}/.test(bodyText3), '비밀(sk-…) 화면 노출 없음')

  // 8) 스크린샷.
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('shot:', OUT)
} catch (e) {
  console.error('ERR', e.message)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
