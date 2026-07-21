/* 스펙 196 e2e — 문제집 목록 최근순 정렬 + 검색 + 페이징.
   API: created desc 정렬 · q 부분검색(이스케이프) · limit/offset · get_dataset 단건.
   UI: 검색창으로 필터 · 최근 생성이 상단.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-list-196.mjs */
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

// 고유 태그로 3개 순차 생성(created 시차) — TAG-1(가장 먼저) … TAG-3(가장 최근)
const TAG = `lst${S}`
const made = []
for (let i = 1; i <= 3; i++) {
  const d = await (await api('/eval/datasets', { method: 'POST', body: JSON.stringify({ name: `${TAG}-${i}`, kind: 'agent' }) })).json()
  made.push(d)
  await new Promise((r) => setTimeout(r, 60))
}
ok(made.every((d) => d?.id), '준비: 3개 문제집 생성')

// ── API 1) 최근순 정렬 + q 검색 ──
const page1 = await (await api(`/eval/datasets?q=${encodeURIComponent(TAG)}&limit=20&offset=0`)).json()
ok(page1?.total === 3, `1a q 검색 total=3 (got ${page1?.total})`)
ok(page1?.items?.[0]?.name === `${TAG}-3`, `1b 최근 생성이 맨 위 (got ${page1?.items?.[0]?.name})`)
ok(page1?.items?.[2]?.name === `${TAG}-1`, `1c 가장 오래된 게 맨 아래 (got ${page1?.items?.[2]?.name})`)

// ── API 2) 페이징 limit/offset ──
const p2a = await (await api(`/eval/datasets?q=${encodeURIComponent(TAG)}&limit=2&offset=0`)).json()
const p2b = await (await api(`/eval/datasets?q=${encodeURIComponent(TAG)}&limit=2&offset=2`)).json()
ok(p2a?.items?.length === 2 && p2b?.items?.length === 1, `2a 페이징(2+1) (got ${p2a?.items?.length}+${p2b?.items?.length})`)
ok(p2a.items[0].name === `${TAG}-3` && p2b.items[0].name === `${TAG}-1`, '2b 페이지 경계 순서 유지')

// ── API 3) 검색 이스케이프(특수문자 안전) ──
const pEsc = await (await api(`/eval/datasets?q=${encodeURIComponent('%_\\')}&limit=5`)).json()
ok(Array.isArray(pEsc?.items), `3 특수문자 q 안전(주입 없음, total=${pEsc?.total})`)

// ── API 4) get_dataset 단건 + 404 ──
const one = await (await api(`/eval/datasets/${made[0].id}`)).json()
ok(one?.id === made[0].id, '4a get_dataset 단건')
const r404 = await api(`/eval/datasets/00000000-0000-0000-0000-000000000000`)
ok(r404.status === 404, `4b 없는 id → 404 (got ${r404.status})`)

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
  await page.getByText('평가', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  // 5) 검색창 존재 + 검색 필터
  const search = page.getByPlaceholder('문제집 이름·설명 검색')
  ok(await search.count() > 0, '5a 검색창 존재')
  await search.fill(`${TAG}-2`)
  await page.waitForTimeout(1200) // 디바운스
  const t = await bodyText()
  ok(/lst.*-2|-2/.test(t) && new RegExp(`${TAG}-2`).test(t), '5b 검색어로 해당 문제집 필터')
  ok(!new RegExp(`${TAG}-1`).test(t) && !new RegExp(`${TAG}-3`).test(t), '5c 검색어와 안 맞는 문제집은 숨김')
  await page.screenshot({ path: `${OUT}/ev196-search.png` })

  // 6) 검색 지우면 최근순(TAG-3가 TAG-1보다 위)
  await search.fill(TAG)
  await page.waitForTimeout(1200)
  const t2 = await bodyText()
  const i3 = t2.indexOf(`${TAG}-3`), i1 = t2.indexOf(`${TAG}-1`)
  ok(i3 >= 0 && i1 >= 0 && i3 < i1, `6 최근 생성이 위(${TAG}-3 < ${TAG}-1 위치: ${i3}<${i1})`)

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  for (const d of made) if (d?.id) await api(`/eval/datasets/${d.id}`, { method: 'DELETE' }).catch(() => {})
  console.log('CLEANUP', made.map((d) => d?.id).filter(Boolean).length)
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (LIST196_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
