/* 스펙 310 프론트 기능 검증 — rag_meta_contains 판정이 RAG 문제집 케이스 편집기에
   실제로 노출·저장·렌더되는지 브라우저 왕복으로 확인(외형 tsc 아닌 동작; learning: UI 검증은 기능 왕복).

   시나리오(movies-demo 컬렉션 필요 — 스킬로 사전 적재):
     ① 페이지 세션으로 movies-demo 바인딩 RAG 문제집 생성 + rag_meta_contains(movie_id=101) 케이스 등록
        → 백엔드가 새 유형을 계약대로 수납하는지(프론트 union→API 왕복).
     ② UI에서 그 문제집 열기 → 케이스 Tag가 assertLabel로 "엔티티 movie_id=101" 렌더(라벨 배선).
     ③ 케이스 편집 폼 열기 → 판정 유형 Select 드롭다운에 "엔티티 id" 옵션이 뜸(RAG 풀 배선·kind 필터).
     ④ 정리: 문제집 삭제(멱등).

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-310-rag-meta-assert.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/verify-310.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const notes = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const note = (m) => { console.log('  ..  ' + m); notes.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
page.on('pageerror', (e) => consoleErrors.push('PAGEERROR: ' + e.message))

// 페이지 세션(쿠키 동행)으로 /api 직접 호출 — 프론트가 실제 쓰는 계약 그대로.
const api = (path, opts) => page.evaluate(async ({ path, opts }) => {
  const res = await fetch(`/api${path}`, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...opts })
  const body = await res.text()
  let json = null; try { json = JSON.parse(body) } catch { /* non-json */ }
  return { status: res.status, json, body: body.slice(0, 300) }
}, { path, opts })

const DS_NAME = '스펙310 영화 엔티티 검증'
let dsId = null

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- ① 사전조건: movies-demo 컬렉션 + RAG 문제집·meta 케이스 생성 ----------
  const cols = await api('/collections')
  check(cols.status === 200, `컬렉션 목록 조회(${cols.status})`)
  const movies = (cols.json ?? []).find((c) => c.name === 'movies-demo')
  if (!movies) {
    note('movies-demo 컬렉션 없음 — movie-demo 스킬로 먼저 적재 필요. 검증 중단(사전조건).')
    throw new Error('PRECONDITION: movies-demo 컬렉션 부재')
  }
  check(movies.kind === 'entity', `movies-demo=엔티티 컬렉션(kind=${movies.kind})`)

  const created = await api('/eval/datasets', {
    method: 'POST',
    body: JSON.stringify({ name: DS_NAME, kind: 'rag', collection_id: movies.id }),
  })
  check(created.status === 200 || created.status === 201, `RAG 문제집 생성(${created.status})`)
  dsId = created.json?.id
  check(!!dsId && created.json?.kind === 'rag', `문제집 kind=rag 바인딩(id=${dsId?.slice(0, 8)})`)

  // 핵심: 프론트 union의 새 유형을 백엔드가 수납하는지 — rag_meta_contains 케이스 등록.
  const caseRes = await api(`/eval/datasets/${dsId}/cases`, {
    method: 'POST',
    body: JSON.stringify({
      name: '인터스텔라가 검색결과에',
      input: '인터스텔라 크리스토퍼 놀란 우주 시간 상대성',
      asserts: [{ type: 'rag_meta_contains', arg: 'movie_id=101' }],
    }),
  })
  check(caseRes.status === 200 || caseRes.status === 201, `rag_meta_contains 케이스 등록 수납(${caseRes.status})`)
  check(caseRes.json?.asserts?.[0]?.type === 'rag_meta_contains', `저장된 판정 유형 왕복=rag_meta_contains`)

  // 적대: malformed arg는 400으로 거부돼야(러너 ValueError→API 400).
  const badCase = await api(`/eval/datasets/${dsId}/cases`, {
    method: 'POST',
    body: JSON.stringify({ name: 'malformed', input: 'x', asserts: [{ type: 'rag_meta_contains', arg: 'movie_id' }] }),
  })
  check(badCase.status >= 400 && badCase.status < 500, `malformed arg(등호 없음) → 4xx 거부(${badCase.status})`)

  // ---------- ② UI에서 문제집 열기 → 케이스 Tag가 assertLabel로 렌더 ----------
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  await page.getByRole('menuitem', { name: '평가', exact: true }).first().click()
    .catch(async () => { await page.getByText('평가', { exact: true }).first().click() })
  await page.waitForTimeout(800)
  // RAG 문제집은 'RAG 평가' 탭(에이전트 문제집과 분리 — kind별 탭).
  await page.getByRole('tab', { name: 'RAG 평가' }).click().catch(() => {})
  await page.waitForTimeout(700)

  // 디버그: 현재 화면 상태 덤프
  await page.screenshot({ path: '/tmp/verify-310-debug.png', fullPage: false })
  const heading = await page.getByRole('banner').getByRole('heading').first().innerText().catch(() => '?')
  const tabTexts = await page.getByRole('tab').allInnerTexts().catch(() => [])
  const rowTexts = await page.locator('.ant-table-row').allInnerTexts().catch(() => [])
  note(`화면 heading=${heading} · 탭=[${tabTexts.join('|')}] · 행수=${rowTexts.length}`)
  rowTexts.slice(0, 8).forEach((t) => note(`  행: ${t.replace(/\n/g, ' ⋅ ').slice(0, 90)}`))

  const dsRow = page.locator('.ant-table-row').filter({ hasText: DS_NAME }).first()
  check((await dsRow.count()) > 0, `문제집 목록에 '${DS_NAME}' 행 노출`)
  await dsRow.click()
  await page.waitForTimeout(1000)

  // assertLabel 배선: 케이스 판정이 "엔티티 movie_id=101" 문장 Tag로 렌더(raw 유형명 아님).
  const metaTag = page.getByText('엔티티 movie_id=101', { exact: false }).first()
  check((await metaTag.count()) > 0, '케이스 판정 Tag가 assertLabel "엔티티 movie_id=101"로 렌더(라벨 배선)')

  // ---------- ③ 케이스 편집 폼 → 판정 유형 Select에 "엔티티 id" 옵션 ----------
  // 케이스 행의 편집 버튼(연필) 클릭 → CaseForm 진입. 없으면 '문제 추가'로 신규 폼.
  const editBtn = page.getByRole('button', { name: /수정|편집/ }).first()
  if (await editBtn.count()) {
    await editBtn.click()
  } else {
    await page.getByRole('button', { name: /문제 추가|추가/ }).first().click().catch(() => {})
  }
  await page.waitForTimeout(700)

  // 판정 유형 Select(width 148)을 열어 드롭다운 옵션에 "엔티티 id"가 있는지.
  const typeSelect = page.locator('.ant-select').filter({ hasText: /엔티티|답변|RAG|근거|유사도/ }).first()
  if (!(await typeSelect.count())) {
    // 폴백: 편집 폼 안의 첫 Select
    note('유형 Select 텍스트 매칭 실패 — 폼 내 첫 Select로 폴백')
  }
  await (await typeSelect.count() ? typeSelect : page.locator('.ant-select').first()).click()
  await page.waitForTimeout(500)
  // 열린 드롭다운의 옵션 텍스트 수집 — "엔티티 id"가 RAG 그룹에 있어야.
  const optTexts = await page.locator('.ant-select-item-option-content').allInnerTexts()
  note(`유형 옵션: ${optTexts.join(' / ').slice(0, 160)}`)
  check(optTexts.some((t) => t.includes('엔티티 id')), '판정 유형 드롭다운에 "엔티티 id" 옵션 노출(RAG 풀·kind 필터 배선)')
  // RAG 문제집이므로 도구(trace_*) 옵션은 없어야(kind 필터 fail-closed).
  check(!optTexts.some((t) => t.includes('도구') || t.includes('노드')), 'RAG 문제집엔 도구/노드(trace_*) 옵션 숨김(kind 필터)')

  await page.screenshot({ path: OUT, fullPage: false })

  // ---------- 콘솔 치명 에러 ----------
  const fatal = consoleErrors.filter((e) =>
    /PAGEERROR|Cannot read|is not a function|undefined is not|Maximum update depth|Rendered more hooks|Rendered fewer hooks/i.test(e),
  )
  check(fatal.length === 0, `콘솔 치명 에러 0(전체 ${consoleErrors.length}, 치명 ${fatal.length})`)
  if (fatal.length) fatal.slice(0, 5).forEach((e) => console.log('    ! ' + e.slice(0, 160)))
} catch (e) {
  console.log('SCRIPT_ERROR: ' + (e?.stack ?? e))
  fails.push('스크립트 예외: ' + (e?.message ?? e))
} finally {
  // ---------- ④ 정리: 문제집 삭제(멱등) ----------
  if (dsId) {
    try {
      const d = await api(`/eval/datasets/${dsId}`, { method: 'DELETE' })
      console.log(`  ..  정리: 문제집 삭제(${d.status})`)
    } catch (e) { console.log('  ..  정리 실패: ' + (e?.message ?? e)) }
  }
  await browser.close()
}

console.log('')
console.log(`스크린샷: ${OUT}`)
if (notes.length) console.log(`참고: ${notes.length}건`)
if (fails.length) {
  console.log(`\nFAIL: ${fails.length}건`)
  fails.forEach((f) => console.log('  - ' + f))
  process.exit(1)
}
console.log('\nVERIFY310_OK — rag_meta_contains 판정 API 수납·assertLabel 렌더·RAG 풀 노출 정착')
