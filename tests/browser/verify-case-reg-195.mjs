/* 스펙 195 e2e — 케이스 등록 UX 4건.
   1) 카드 'N개 기준' 배지 제거(질문이 제목).
   2) rag_source_contains 근거 파일명 AutoComplete(등록 파일 옵션).
   3) '문제 이름' 입력 제거 — name 없이 생성 시 해시(case-…), update 미전송 시 보존.
   4) 드로어 상단 'AI 출제' 버튼.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-case-reg-195.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-loveqoo-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'
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

// ── 3) 백엔드 name 해시/보존(API 왕복) ──
const ds = await (await api('/eval/datasets', { method: 'POST', body: JSON.stringify({ name: `ev195-${S}`, kind: 'rag', collection_id: col?.id }) })).json()
// name 없이 케이스 생성 → 해시
const c1 = await (await api(`/eval/datasets/${ds.id}/cases`, { method: 'POST', body: JSON.stringify({ input: '환불 정책이 무엇인가요?', asserts: [{ type: 'no_error' }] }) })).json()
ok(typeof c1?.name === 'string' && /^case-[0-9a-f]{8}$/.test(c1.name), `3a name 없이 생성 → 해시 (got ${c1?.name})`)
// update name 없이 → 기존 해시 보존
const c1b = await (await api(`/eval/cases/${c1.id}`, { method: 'PATCH', body: JSON.stringify({ input: '수정된 질문', asserts: [{ type: 'no_error' }] }) })).json()
ok(c1b?.name === c1.name, `3b update 미전송 시 해시 보존 (${c1.name} → ${c1b?.name})`)
// 두 번째 케이스(카드 표시용)
await api(`/eval/datasets/${ds.id}/cases`, { method: 'POST', body: JSON.stringify({ input: '배송은 며칠 걸리나요?', asserts: [{ type: 'rag_hits_gte', arg: '1' }, { type: 'no_error' }] }) })

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
  ok(await waitFor(new RegExp(`ev195-${S}`)), '평가 목록에 문제집 노출')

  await openDataset(`ev195-${S}`)
  const dt = await bodyText()
  // 1) 'N개 기준' 배지 없음
  ok(!/\d+개 기준/.test(dt), "1 카드에 'N개 기준' 배지 없음")
  // 카드 제목 = 질문
  ok(/환불 정책이 무엇인가요|수정된 질문/.test(dt) && /배송은 며칠 걸리나요/.test(dt), '카드 제목이 질문(input)')
  // 4) 상단 'AI 출제' 버튼
  ok(await page.getByRole('button', { name: 'AI 출제' }).count() > 0, "4 상단 'AI 출제' 버튼 존재")
  await page.screenshot({ path: `${OUT}/ev195-drawer.png` })

  // 2 + 3) '문제 추가' → 이름칸 없음 + 파일명 AutoComplete
  await page.getByRole('button', { name: '문제 추가' }).first().click()
  await page.waitForTimeout(600)
  // 3) '문제 이름' placeholder 없음
  ok(await page.getByPlaceholder(/문제 이름/).count() === 0, "3c 폼에 '문제 이름' 입력칸 없음")
  ok(await page.getByPlaceholder(/이 질문이 문제 제목/).count() > 0, '3d 질문 입력칸만(제목 겸용 안내)')
  // 유형을 '근거 파일명'으로 → AutoComplete 옵션
  const firstSel = page.locator('.ant-drawer .ant-select').filter({ hasText: /답변|오류|검색|근거|AI/ }).last()
  await firstSel.click()
  await page.waitForTimeout(300)
  const srcOpt = page.locator('.ant-select-item-option').filter({ hasText: '근거 파일명' }).first()
  if (await srcOpt.count()) {
    await srcOpt.click()
    await page.waitForTimeout(400)
    // AutoComplete 클릭 → 파일명 옵션 드롭다운
    const ac = page.locator('.ant-drawer input[role="combobox"]').last()
    await ac.click().catch(() => {})
    await page.waitForTimeout(400)
    const acText = await bodyText()
    ok(/근거 파일명에/.test(acText), '2a 근거 파일명 문장형')
    // 파일명 옵션이 하나라도 뜨는지(컬렉션 문서)
    const optCount = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').count()
    ok(optCount > 0, `2b 파일명 AutoComplete 옵션 노출 (${optCount})`)
    await page.screenshot({ path: `${OUT}/ev195-filename-ac.png` })
  } else {
    ok(false, "2 '근거 파일명' 유형 옵션을 찾지 못함")
    await page.screenshot({ path: `${OUT}/ev195-nosrc.png` })
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
console.log(fails.length === 0 ? '\n✅ ALL PASS (CASEREG195_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
