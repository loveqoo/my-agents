/* 스펙 198 e2e — 청크 정책 수정 제거(생성 후 불변).
   (A) API 왕복: PUT에 chunk_size/overlap을 보내도 무시(값 불변) + 별명·설명은 수정됨.
   (B) UI: 컬렉션 편집 모달에 청크 크기/겹침 입력 필드 없음 · 안내 문구 갱신.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-chunk-immutable-198.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-loveqoo-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]
const api = (path, opts = {}) => fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', Cookie: cookie, ...(opts.headers || {}) } })

// ── (A) API 왕복: 청크 수정 무시 ───────────────────────────────────────────
const cols = await (await api('/collections')).json().catch(() => [])
const col = (Array.isArray(cols) ? cols : []).find((c) => c.kind !== 'entity') ?? cols[0]
ok(!!col, `준비: 컬렉션 (${col?.name ?? '없음'})`)
const origSize = col.chunk_size
const origOverlap = col.chunk_overlap
const origAlias = col.alias ?? ''
const tag = `t198`
// 구 클라이언트가 chunk_size/overlap를 보내는 상황을 재현 — 스키마에서 필드가 사라져 무시돼야.
const put = await api(`/collections/${col.id}`, {
  method: 'PUT',
  body: JSON.stringify({ alias: tag, description: (col.description ?? '') + '', chunk_size: origSize + 1234, chunk_overlap: origOverlap + 555 }),
})
ok(put.ok, `A0 PUT 200 (실제 ${put.status})`)
const after = await (await api(`/collections/${col.id}`)).json()
ok(after.chunk_size === origSize, `A1 chunk_size 불변 (${origSize} → ${after.chunk_size})`)
ok(after.chunk_overlap === origOverlap, `A2 chunk_overlap 불변 (${origOverlap} → ${after.chunk_overlap})`)
ok(after.alias === tag, `A3 별명은 수정됨 (${after.alias})`)
// 원복
await api(`/collections/${col.id}`, { method: 'PUT', body: JSON.stringify({ alias: origAlias }) })

// ── (B) UI: 편집 모달에 청크 필드 없음 ──────────────────────────────────────
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1000 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const bodyText = () => page.locator('body').innerText()
const waitFor = async (re, ms = 12000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await bodyText())) return true; await page.waitForTimeout(300) } return false }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1000)

  // 편집 모달 열기 — 행 액션의 편집 아이콘(antd EditOutlined = .anticon-edit).
  const row = page.locator('tbody tr.ant-table-row').filter({ hasText: col.name }).first()
  await row.waitFor({ state: 'visible', timeout: 8000 }).catch(() => {})
  await row.locator('button:has(.anticon-edit)').first().click()
  const opened = await waitFor(/컬렉션 편집/, 6000)
  ok(opened, 'B1 컬렉션 편집 모달 열림')
  await page.waitForTimeout(700)  // 모달 슬라이드-인 완료 대기(스샷 눈확인용)
  const mt = await bodyText()
  await page.locator('.ant-modal').first().screenshot({ path: `${OUT}/edit-modal-198.png` }).catch(() => page.screenshot({ path: `${OUT}/edit-modal-198.png` }))
  // 편집 모달 안엔 청크 입력(InputNumber)이 없어야 — 청크 정책은 생성 후 불변.
  ok((await page.locator('.ant-modal .ant-input-number').count()) === 0, 'B2 편집 모달 내 InputNumber(청크 입력) 0개')
  ok(/생성 후 변경할 수 없습니다/.test(mt), 'B3 불변 안내 문구 노출')
  // 별명 입력은 여전히 있어야(수정 가능 유지)
  ok((await page.locator('.ant-modal input').count()) > 0, 'B4 별명 입력은 유지(수정 가능)')
  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (CHUNKIMMUTABLE198_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
