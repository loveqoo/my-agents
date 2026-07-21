/* 스펙 194 e2e — 채점 기준(assert) 편집 UX: AND 명확화 + 문장형 인라인 폼 + 카드 표시 일관.
   A) AND 배지("모든 기준을 만족") + "그리고" 커넥터(기준 2개+).
   B) 문장형: 프리필 [오류 없음·비어있지 않음]이 문장으로. 유형 select(카테고리 그룹) → rag_hits 전환 시
      "검색 결과가 [N]건 [이상/이하]" 위젯 노출.
   C) lte 왕복: rag_hits_lte 케이스가 카드에 "검색 결과 2건 이하"로.
   E) 카드 표시 = assertLabel(raw type "no_error"/"rag_hits_lte" 노출 안 함).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-assert-ux-194.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
const S = Date.now().toString(36)

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]
const api = (path, opts = {}) => fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', Cookie: cookie, ...(opts.headers || {}) } })

const cols = await (await api('/collections')).json().catch(() => [])
const col = (Array.isArray(cols) ? cols : [])[0]
ok(!!col, `준비: 실 컬렉션 존재 (${col?.name ?? '없음'})`)

// rag 문제집 + lte/gte 케이스 (백엔드 lte 저장 왕복 → 카드 문장 확인)
const ds = await (await api('/eval/datasets', { method: 'POST', body: JSON.stringify({ name: `ev194-${S}`, kind: 'rag', collection_id: col?.id }) })).json()
const c1 = await (await api(`/eval/datasets/${ds.id}/cases`, { method: 'POST', body: JSON.stringify({ name: 'lte케이스', input: '문서 몇 건?', asserts: [{ type: 'rag_hits_lte', arg: '2' }, { type: 'no_error' }] }) })).json()
ok(c1?.asserts?.some((a) => a.type === 'rag_hits_lte' && a.arg === '2'), `준비: rag_hits_lte 케이스 저장 왕복 (got ${JSON.stringify(c1?.asserts?.map((a) => a.type))})`)
await api(`/eval/datasets/${ds.id}/cases`, { method: 'POST', body: JSON.stringify({ name: 'score케이스', input: '유사도', asserts: [{ type: 'rag_score_gte', arg: '0.4' }, { type: 'rag_source_contains', arg: 'AB테스트.md' }] }) })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1100 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const bodyText = () => page.locator('body').innerText()
const waitFor = async (re, ms = 20000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await bodyText())) return true; await page.waitForTimeout(500) } return false }
const openDataset = async (name) => {
  const row = page.locator('tbody tr.ant-table-row').filter({ hasText: name }).first()
  await row.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})
  await row.scrollIntoViewIfNeeded().catch(() => {})
  await row.click({ timeout: 8000 }).catch(async () => { await row.click({ force: true }).catch(() => {}) })
  await page.waitForTimeout(900)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('평가', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  ok(await waitFor(new RegExp(`ev194-${S}`)), '평가 목록에 문제집 노출')

  // ── E+C: 저장된 케이스 카드가 문장형(assertLabel) ──
  await openDataset(`ev194-${S}`)
  const dt = await bodyText()
  ok(/검색 결과 2건 이하/.test(dt), 'C 카드에 "검색 결과 2건 이하"(rag_hits_lte 왕복)')
  ok(/오류 없음/.test(dt), 'E 카드에 "오류 없음"(no_error 문장화)')
  ok(/유사도 0\.4 이상/.test(dt), 'E 카드에 "유사도 0.4 이상"(rag_score_gte)')
  ok(/근거 파일 "AB테스트\.md"/.test(dt), 'E 카드에 근거 파일 문장')
  ok(!/rag_hits_lte|no_error|rag_score_gte|rag_source_contains/.test(dt), 'E raw type 문자열 노출 안 함')
  await page.screenshot({ path: `${OUT}/ev194-cards.png` })

  // ── A+B: "문제 추가" → CaseForm 문장형 ──
  await page.getByRole('button', { name: '문제 추가' }).first().click()
  await page.waitForTimeout(700)
  const ft = await bodyText()
  ok(/모든.*기준을 만족해야 이 문제가 통과/.test(ft), 'A AND 배지("모든 기준을 만족")')
  ok(/실행 오류가 없어야 통과/.test(ft), 'B 프리필 문장화(오류 없음)')
  ok(/답변이 비어있지 않아야 통과/.test(ft), 'B 프리필 문장화(비어있지 않음)')
  ok(/그리고/.test(ft), 'A "그리고" 커넥터(기준 2개)')
  await page.screenshot({ path: `${OUT}/ev194-form-prefill.png` })

  // 첫 기준 유형 select를 열어 카테고리 그룹 + RAG 검색 결과 건수 선택 → 문장 위젯 전환
  const firstSel = page.locator('.ant-drawer .ant-select').first()
  await firstSel.click()
  await page.waitForTimeout(400)
  const optText = await page.locator('.ant-select-dropdown').last().innerText().catch(() => '')
  ok(/답변|RAG|AI/.test(optText), `B 유형 select 카테고리 그룹 (${optText.replace(/\n/g, '·').slice(0, 60)})`)
  const hitsOpt = page.locator('.ant-select-item-option').filter({ hasText: '검색 결과 건수' }).first()
  if (await hitsOpt.count()) {
    await hitsOpt.click()
    await page.waitForTimeout(500)
    const ft2 = await bodyText()
    ok(/검색 결과가/.test(ft2), 'B rag_hits 전환 시 "검색 결과가" 문장')
    ok(/여야 통과/.test(ft2), 'B "…여야 통과" 문장 꼬리')
    // 연산자 select(이상/이하) 존재
    const opSel = page.locator('.ant-drawer .ant-select').filter({ hasText: /이상|이하/ }).first()
    ok(await opSel.count() > 0, 'B 연산자 select(이상/이하) 노출')
    await page.screenshot({ path: `${OUT}/ev194-form-sentence.png` })
  } else {
    ok(false, 'B "검색 결과 건수" 옵션을 찾지 못함')
    await page.screenshot({ path: `${OUT}/ev194-form-nooption.png` })
  }

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  if (ds?.id) await api(`/eval/datasets/${ds.id}`, { method: 'DELETE' }).catch(() => {})
  console.log('CLEANUP', ds?.id)
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (ASSERTUX194_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
