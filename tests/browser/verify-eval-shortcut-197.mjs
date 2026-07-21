/* 스펙 197 e2e — 컬렉션 상세 '평가하기' 단축 진입.
   컬렉션 문서 드로어 → '이 컬렉션 평가하기' → 평가 화면 전환 + 새 문제집 모달(rag+컬렉션 프리필)
   → 이름 넣고 생성 → rag 문제집(collection_id 고정) 확인.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-eval-shortcut-197.mjs */
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
const list = Array.isArray(cols) ? cols : []
const col = list.find((c) => c.doc_count > 0) ?? list[0]  // 평가하려면 문서가 있어야(스펙 197 후속)
const emptyCol = list.find((c) => c.doc_count === 0)
ok(!!col, `준비: 문서 있는 컬렉션 (${col?.name ?? '없음'}, ${col?.doc_count}건)`)
const dsName = `ev197-${S}`
let createdId = null

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1000 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const bodyText = () => page.locator('body').innerText()
const waitFor = async (re, ms = 15000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await bodyText())) return true; await page.waitForTimeout(400) } return false }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 1) RAG 컬렉션 → 컬렉션 상세(문서 관리) 열기
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  const row = page.locator('tbody tr.ant-table-row').filter({ hasText: col.name }).first()
  await row.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})
  await row.click({ timeout: 8000 }).catch(async () => { await row.click({ force: true }).catch(() => {}) })
  await page.waitForTimeout(800)
  ok(await waitFor(new RegExp(`문서 관리 · ${col.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)), '1 컬렉션 상세(문서 관리) 드로어 열림')

  // 2) 헤더 우측 '평가하기' 버튼(문서 있음 → 활성)
  const evalBtn = page.getByRole('button', { name: '평가하기' })
  ok(await evalBtn.count() > 0, "2a 헤더 '평가하기' 버튼 노출")
  ok(await evalBtn.first().isEnabled(), '2b 문서 있는 컬렉션 → 활성')
  await evalBtn.first().click()
  await page.waitForTimeout(1200)

  // 3) 평가 화면 전환 + 새 문제집 모달(rag + 컬렉션 프리필)
  ok(await waitFor(/새 문제집/, 8000), '3a 새 문제집 모달 자동 열림')
  const mt = await bodyText()
  ok(/RAG 컬렉션 시험/.test(mt), '3b 종류=RAG로 프리필')
  ok(new RegExp(col.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).test(mt), `3c 대상 컬렉션(${col.name}) 프리필`)
  await page.screenshot({ path: `${OUT}/ev197-modal.png` })

  // 4) 이름 넣고 생성
  await page.getByPlaceholder(/이름 \(예:/).fill(dsName)
  await page.getByRole('button', { name: '만들기' }).click()
  await page.waitForTimeout(1500)

  // 5) 생성된 rag 문제집 collection_id 고정 확인(API)
  const listed = await (await api(`/eval/datasets?q=${encodeURIComponent(dsName)}`)).json()
  const made = (listed?.items ?? []).find((d) => d.name === dsName)
  createdId = made?.id
  ok(!!made, '5a 문제집 생성됨')
  ok(made?.kind === 'rag' && made?.collection_id === col.id, `5b rag+컬렉션 고정 (kind=${made?.kind}, coll=${made?.collection_id === col.id})`)

  // 2c) 문서 0개 컬렉션 → '평가하기' 비활성(평가할 근거 없음, 스펙 197 후속)
  if (emptyCol) {
    await page.getByText('RAG 컬렉션', { exact: true }).first().click()
    await page.waitForTimeout(1000)
    const erow = page.locator('tbody tr.ant-table-row').filter({ hasText: emptyCol.name }).first()
    await erow.click({ force: true })
    await page.waitForTimeout(900)
    const eb = page.getByRole('button', { name: '평가하기' })
    ok(await eb.count() > 0 && !(await eb.first().isEnabled()), `2c 문서 0개(${emptyCol.name}) → 평가하기 비활성`)
  } else {
    ok(true, '2c 빈 컬렉션 없음 — 비활성 검증 스킵')
  }

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  if (createdId) await api(`/eval/datasets/${createdId}`, { method: 'DELETE' }).catch(() => {})
  console.log('CLEANUP', createdId)
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (EVALSHORTCUT197_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
