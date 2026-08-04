/* 스펙 312 프론트 기능 검증 — 재인덱싱 모달을 실제로 구동해 효과를 단언(외형 아닌 동작).
   시나리오:
     ① 페이지 세션 API로 문서 컬렉션(mock-embed) 생성 + 문서 업로드(재인덱싱 대상 확보).
     ② UI: RAG 컬렉션 → 문서 임베딩 탭 → 행의 재인덱싱(↻) 버튼 → 모달에서 임베딩 모델을 e5로 변경 →
        '재인덱싱 실행' → 성공.
     ③ 단언(왕복): reindex POST 발화 · 컬렉션 embedding_model_name이 e5로 바뀜 · 재인덱싱 이력 1건.
     ④ 정리: 컬렉션 삭제.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-312-reindex.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/verify-312.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const COL = 'verify312-ui'
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
const reqs = []
page.on('request', (r) => reqs.push(`${r.method()} ${r.url()}`))

const api = (path, opts) => page.evaluate(async ({ path, opts }) => {
  const res = await fetch(`/api${path}`, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...opts })
  const body = await res.text()
  let json = null; try { json = JSON.parse(body) } catch { /* non-json */ }
  return { status: res.status, json }
}, { path, opts })

let cid = null
try {
  // ── 로그인 ──
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ── ① 사전조건: 문서 컬렉션(mock) + 문서 업로드 ──
  const models = (await api('/models?kind=embedding')).json ?? []
  const mock = models.find((m) => m.name === 'mock-embed')
  const e5 = models.find((m) => m.name !== 'mock-embed')
  check(!!mock && !!e5, `임베딩 모델 2종 확보(mock+${e5?.name?.slice(0, 18)})`)
  if (!e5) throw new Error('PRECONDITION: e5 모델 없음')

  // 기존 정리
  const cols0 = (await api('/collections')).json ?? []
  const prev = cols0.find((c) => c.name === COL)
  if (prev) await api(`/collections/${prev.id}`, { method: 'DELETE' })

  const created = await api('/collections', {
    method: 'POST',
    body: JSON.stringify({ name: COL, kind: 'document', embedding_model_id: mock.id, chunk_size: 1000, chunk_overlap: 200 }),
  })
  check(created.status === 201, `문서 컬렉션 생성(${created.status})`)
  cid = created.json.id

  // 문서 업로드(멀티파트) — 페이지 컨텍스트 FormData.
  const up = await page.evaluate(async (id) => {
    const fd = new FormData()
    const text = Array.from({ length: 5 }, (_, i) => `문단 ${i}: 재인덱싱은 원본에서 다시 임베딩한다. 검색 품질을 높이려면 임베딩 모델을 바꿔가며 테스트한다.`).join('\n\n')
    fd.append('file', new Blob([text], { type: 'text/plain' }), 'reindex-ui.txt')
    const res = await fetch(`/api/collections/${id}/documents`, { method: 'POST', credentials: 'include', body: fd })
    return res.status
  }, cid)
  check(up === 201, `문서 업로드(${up})`)
  const before = (await api(`/collections/${cid}`)).json
  check(before.embedding_model_name === 'mock-embed', `초기 모델=mock-embed`)

  // ── ② UI 구동: RAG 컬렉션 → 재인덱싱 모달 ──
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('menuitem', { name: 'RAG 컬렉션', exact: true }).first().click()
    .catch(async () => { await page.getByText('RAG 컬렉션', { exact: true }).first().click() })
  await page.waitForTimeout(800)
  // 문서 임베딩 탭(기본) — 우리 컬렉션 행
  const row = page.locator('.ant-table-row').filter({ hasText: COL }).first()
  check(await row.count() > 0, `컬렉션 행 '${COL}' 노출`)
  // 행의 재인덱싱 버튼(sync 아이콘) — 액션 셀의 버튼들 중 tooltip '재인덱싱'.
  await row.locator('button').filter({ has: page.locator('[aria-label="sync"], .anticon-sync') }).first().click()
    .catch(async () => {
      // 폴백: 액션 버튼 중 3번째(검색·점검·편집·재인덱싱·삭제 순 — sync는 편집 뒤)
      const btns = row.locator('td:last-child button')
      await btns.nth(3).click()
    })
  await page.waitForTimeout(600)
  const modal = page.locator('.ant-modal').filter({ hasText: '재인덱싱' }).first()
  check(await modal.count() > 0, '재인덱싱 모달 열림')

  // 임베딩 모델 Select을 e5로 변경
  await modal.locator('.ant-select').first().click()
  await page.waitForTimeout(400)
  await page.locator('.ant-select-item-option').filter({ hasText: e5.name }).first().click()
  await page.waitForTimeout(300)

  // '재인덱싱 실행'
  const mark = reqs.length
  await modal.getByRole('button', { name: '재인덱싱 실행' }).click()
  // 서버 동기 처리(잠금→재임베딩(e5)→스왑) — 완료 대기
  await page.waitForTimeout(3500)

  // ── ③ 단언 ──
  const reindexFired = reqs.slice(mark).some((u) => /POST .*\/collections\/[^/]+\/reindex\b/.test(u))
  check(reindexFired, '재인덱싱 POST 발화(모달 실행이 실제 API 호출)')
  const after = (await api(`/collections/${cid}`)).json
  check(after.embedding_model_name === e5.name, `컬렉션 모델이 e5로 스왑(${after.embedding_model_name?.slice(0, 20)})`)
  check(after.status === 'ready', `재인덱싱 후 status=ready(${after.status})`)
  const events = (await api(`/collections/${cid}/reindex-events`)).json ?? []
  check(events.length >= 1, `재인덱싱 이력 ${events.length}건 기록`)
  if (events[0]) note(`이력: ${events[0].from_model_name}→${events[0].to_model_name} status=${events[0].status} count=${events[0].chunk_count}`)

  await page.screenshot({ path: OUT, fullPage: false })

  const fatal = consoleErrors.filter((e) => /PAGEERROR|Cannot read|is not a function|undefined is not|Maximum update depth|Rendered (more|fewer) hooks/i.test(e))
  check(fatal.length === 0, `콘솔 치명 에러 0(전체 ${consoleErrors.length}, 치명 ${fatal.length})`)
  if (fatal.length) fatal.slice(0, 5).forEach((e) => console.log('    ! ' + e.slice(0, 160)))
} catch (e) {
  console.log('SCRIPT_ERROR: ' + (e?.stack ?? e))
  fails.push('스크립트 예외: ' + (e?.message ?? e))
} finally {
  if (cid) { try { await api(`/collections/${cid}`, { method: 'DELETE' }) } catch { /* noop */ } }
  await browser.close()
}

console.log('')
console.log(`스크린샷: ${OUT}`)
if (fails.length) {
  console.log(`\nFAIL: ${fails.length}건`)
  fails.forEach((f) => console.log('  - ' + f))
  process.exit(1)
}
console.log('\nVERIFY312_UI_OK — 재인덱싱 모달 구동→모델 스왑·이력 기록 기능 왕복 정착')
