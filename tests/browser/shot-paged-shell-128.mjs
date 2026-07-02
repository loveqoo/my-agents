/* 스펙 128 검증 — 공용 PagedListShell(admin/src/admin/views/PagedListShell.tsx)로 세션·컬렉션 문서
   목록을 통일. 시스템 Chrome.

   사전 시드(bash, 이 스크립트 실행 전에 별도로 수행):
   - 컬렉션 1개(name='v128e2e-col') + 문서 15건(filename='v128e2e-doc-N.txt', status='ready')를
     collections/documents 테이블에 직접 SQL INSERT.
   세션 화면(S1~S5)은 별도 시드 없이 기존 sessions 데이터로 검증한다(카운트는 실측 비교).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-paged-shell-128.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_SESSIONS = process.env.OUT_SESSIONS ?? '/tmp/paged-128-sessions.png'
const OUT_DOCS = process.env.OUT_DOCS ?? '/tmp/paged-128-docs.png'
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

  /* ---------- 세션 화면 (S1~S5) ---------- */
  await page.getByText('세션', { exact: true }).first().click()
  await page.waitForTimeout(800)

  // S1: status Radio 버튼("전체 (N)" 형태 라벨) 존재.
  const allRadio = page.getByText(/^전체 \(\d+\)$/).first()
  const allRadioVisible = await allRadio.isVisible().catch(() => false)
  check(allRadioVisible, 'S1: status Radio "전체 (N)" 라벨 존재')
  let radioAllCount = null
  if (allRadioVisible) {
    const t = await allRadio.innerText()
    radioAllCount = t.match(/\((\d+)\)/)?.[1] ?? null
  }

  // S2: "전체 N건" 총계 줄 표시(N은 Radio의 전체 카운트와 일치).
  await page.waitForTimeout(500)
  const bodyText1 = await page.locator('#root').innerText().catch(() => '')
  const totalMatch = bodyText1.match(/전체 (\d+)건/)
  check(!!totalMatch, 'S2: "전체 N건" 총계 줄 표시')
  check(!!totalMatch && !!radioAllCount && totalMatch[1] === radioAllCount,
    `S2: 총계 N(${totalMatch?.[1]})이 Radio 전체 카운트(${radioAllCount})와 일치`)

  // S3: 검색 Input에 "test-xyz-없는검색어" 입력 → 1초 대기 → "일치 0건" + 빈 테이블 문구.
  const sessionSearch = page.getByPlaceholder('세션 ID·유저·에이전트 검색')
  await sessionSearch.fill('test-xyz-없는검색어')
  await page.waitForTimeout(1000)
  const bodyText2 = await page.locator('#root').innerText().catch(() => '')
  check(/일치 0건/.test(bodyText2), 'S3: 검색 결과 "일치 0건" 표시')
  check(bodyText2.includes('조건에 맞는 세션이 없습니다'), 'S3: 빈 테이블 문구 "조건에 맞는 세션이 없습니다" 표시')

  // S4: 검색어 보존 — Radio "라이브" 클릭 후에도 검색 Input 값이 유지되는지.
  const liveRadio = page.getByText(/^라이브 \(\d+\)$/).first()
  await liveRadio.click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(800)
  const searchValAfter = await sessionSearch.inputValue().catch(() => '')
  check(searchValAfter === 'test-xyz-없는검색어', `S4: Radio 전환 후 검색어 보존(실측 "${searchValAfter}")`)

  // S5: 검색어 clear → 총계가 다시 "전체 N건"으로.
  await sessionSearch.fill('')
  await page.waitForTimeout(1000)
  const bodyText3 = await page.locator('#root').innerText().catch(() => '')
  check(/전체 \d+건/.test(bodyText3), 'S5: 검색어 clear 후 "전체 N건" 총계로 복귀')

  await page.screenshot({ path: OUT_SESSIONS, fullPage: false })
  console.log('shot:', OUT_SESSIONS)

  /* ---------- 컬렉션 문서 (C1~C4) ---------- */
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(800)

  // C1: 목록에 v128e2e-col 행 존재 → 행 클릭(문서 관리 드로어 열림).
  const colRow = page.locator('tr', { hasText: 'v128e2e-col' }).first()
  const colRowVisible = await colRow.isVisible().catch(() => false)
  check(colRowVisible, 'C1: 목록에 v128e2e-col 행 존재')
  if (colRowVisible) {
    await colRow.click({ timeout: 8000 })
  }
  await page.waitForTimeout(500)
  const drawerTitleVisible = await page.getByText(/문서 관리 · v128e2e-col/).first().isVisible().catch(() => false)
  check(drawerTitleVisible, 'C1: 문서 관리 드로어 열림("문서 관리 · v128e2e-col")')

  // C2: 드로어 안에 "전체 15건" 총계 + 페이지네이션(.ant-pagination) 존재(10건/쪽).
  // 드로어는 antd Drawer(body에 포털) — #root가 아니라 .ant-drawer-section 스코프로 읽는다.
  // 전환 애니메이션(.25s) + 첫 페이지 fetch 완료를 기다린다(고정 대기 대신 폴링).
  const drawerContent = page.locator('.ant-drawer-section').first()
  await drawerContent.getByText('전체 15건', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  const bodyText4 = await drawerContent.innerText().catch(() => '')
  check(bodyText4.includes('전체 15건'), 'C2: 드로어 총계 "전체 15건" 표시')
  const docsPagination = drawerContent.locator('.ant-pagination').first()
  const docsPaginationVisible = await docsPagination.isVisible().catch(() => false)
  check(docsPaginationVisible, 'C2: 페이지네이션(.ant-pagination) 존재')

  // C3: 2페이지 클릭 → 행 5건(15 - 10). 행 카운트는 드로어 안 tbody만(배경 컬렉션 표와 섞이지 않게).
  if (docsPaginationVisible) {
    await docsPagination.locator('.ant-pagination-item-2').waitFor({ timeout: 8000 }).catch(() => {})
    await docsPagination.locator('.ant-pagination-item-2').click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(1000)
    const rowCount = await drawerContent.locator('tbody tr').count().catch(() => 0)
    check(rowCount === 5, `C3: 2페이지 행 수 5(실측 ${rowCount})`)
  } else {
    check(false, 'C3: 2페이지 행 수 5 (Pagination 없어 스킵)')
  }

  // C4: 검색 Input "doc-3" 입력 → 1초 대기 → "일치 1건".
  const docSearch = page.getByPlaceholder('파일명 부분일치 검색')
  await docSearch.fill('doc-3')
  await drawerContent.getByText('일치 1건', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  const bodyText5 = await drawerContent.innerText().catch(() => '')
  check(/일치 1건/.test(bodyText5), 'C4: 검색 "doc-3" → "일치 1건" 표시')

  await page.screenshot({ path: OUT_DOCS, fullPage: false })
  console.log('shot:', OUT_DOCS)
} catch (e) {
  console.error('ERR', e.message)
  await page.screenshot({ path: OUT_DOCS, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
