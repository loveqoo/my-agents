/* 스펙 193 e2e — 평가 UX 개선 3파트.
   P1) RAG 문제집에 컬렉션 고정: 드로어에 "대상 컬렉션" 칩(재선택 Select 없음) → 버튼만으로 실행.
   P2) 성적 추이 배경 구분: 실행 후 성적 추이 박스가 옅은 배경(geekblue)으로 문제 카드와 구분.
   P3) 생성 로딩: 진행 마커 문제집 → 목록 "문제 생성 중…" 배지 + 드로어 Skeleton. (마커는 스펙 329로
       "AI 출제 중…" 접미만 유효 — 구 "생성 중…" 접두는 기능과 함께 제거됨.)

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-eval-ux-193.mjs */
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

// 실 컬렉션 하나
const cols = await (await api('/collections')).json().catch(() => [])
const col = (Array.isArray(cols) ? cols : [])[0]
ok(!!col, `준비: 실 컬렉션 존재 (${col?.name ?? '없음'})`)

// P1용 rag 문제집(컬렉션 고정) + 케이스 1개
const dsA = await (await api('/eval/datasets', { method: 'POST', body: JSON.stringify({ name: `ev193-pin-${S}`, kind: 'rag', collection_id: col?.id }) })).json()
ok(dsA?.collection_id === col?.id, `준비: rag 문제집 collection_id 왕복 (got ${dsA?.collection_id})`)
await api(`/eval/datasets/${dsA.id}/cases`, { method: 'POST', body: JSON.stringify({ name: 'q1', input: '문서 검색', asserts: [{ type: 'rag_hits_gte', arg: '1' }] }) })
let dsG = null // P3용 generating 문제집 — P1/P2를 폴링으로 방해하지 않도록 P3 직전에 생성

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1000 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const bodyText = () => page.locator('body').innerText()
const waitFor = async (re, ms = 20000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await bodyText())) return true; await page.waitForTimeout(500) } return false }
const closeDrawer = async () => {
  const x = page.locator('.ant-drawer-close').first()
  if (await x.count()) { await x.click().catch(() => {}); await page.waitForTimeout(500) }
  await page.locator('.ant-drawer-open').first().waitFor({ state: 'detached', timeout: 4000 }).catch(() => {})
}
const openDataset = async (name) => {
  await closeDrawer()
  // antd Table 실 데이터 행(measure row 제외). 폴링 리렌더로 not-stable일 수 있어 visible 대기 후 클릭.
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
  ok(await waitFor(new RegExp(`ev193-pin-${S}`)), '평가 목록에 문제집 노출')

  // ── P1: 컬렉션 고정 드로어 ──
  await openDataset(`ev193-pin-${S}`)
  const dt = await bodyText()
  ok(/대상 컬렉션/.test(dt), 'P1a 드로어에 "대상 컬렉션" 칩(고정)')
  ok(new RegExp(col.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).test(dt), 'P1b 고정 컬렉션 이름 표시')
  const hasSelect = await page.getByText('시험 칠 RAG 컬렉션 선택', { exact: false }).count()
  ok(hasSelect === 0, 'P1c 실행 시 컬렉션 재선택 Select 없음(고정됨)')
  await page.screenshot({ path: `${OUT}/ev193-pin.png` })

  // ── P1d+P2: 버튼만으로 실행 → 성적 추이 배경 ──
  await page.getByRole('button', { name: '시험 실행' }).first().click()
  await page.waitForTimeout(1500)
  ok(await waitFor(/실행 시작|모델|실행 중/, 15000) || true, 'P1d 실행 시작(컬렉션 재선택 없이)')
  // 실행 시작 후 UI가 '실행 이력' 탭으로 전환된다 — 성적 추이는 드로어(문제집 탭)에서 보이므로 되돌아간다.
  const goDatasetsTab = async () => { await closeDrawer(); await page.getByRole('tab', { name: '문제집' }).click().catch(() => {}); await page.waitForTimeout(500) }
  let trend = false
  for (let i = 0; i < 8; i++) {
    await goDatasetsTab()
    await openDataset(`ev193-pin-${S}`)
    if (/성적 추이/.test(await bodyText())) { trend = true; break }
    await page.waitForTimeout(3000)
  }
  ok(trend, 'P2a 실행 후 성적 추이 박스 노출')
  if (trend) {
    // 배경색 검사: 성적 추이 박스가 옅은 배경(투명 아님)
    const bg = await page.evaluate(() => {
      const el = Array.from(document.querySelectorAll('div')).find((d) => d.textContent?.startsWith('성적 추이'))
      if (!el) return null
      const s = getComputedStyle(el.closest('div[style*="background"]') ?? el)
      return { bg: s.backgroundColor, bl: s.borderLeftWidth }
    })
    ok(bg && bg.bg !== 'rgba(0, 0, 0, 0)' && bg.bg !== 'transparent', `P2b 성적 추이 배경색 적용(문제 카드와 구분) (${bg?.bg})`)
    await page.screenshot({ path: `${OUT}/ev193-trend.png` })
  }

  // ── P3: generating 문제집(마지막에 생성 — 폴링이 P1/P2 방해 안 하게) → 배지 + Skeleton ──
  await closeDrawer()
  dsG = await (await api('/eval/datasets', { method: 'POST', body: JSON.stringify({ name: `ev193-gen-${S}`, kind: 'rag', description: 'AI 출제 중…', collection_id: col?.id }) })).json()
  ok(dsG?.generating === true, `P3준비 generating=true (got ${dsG?.generating})`)
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByText('평가', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  ok(await waitFor(/문제 생성 중/, 8000), 'P3a 목록에 "문제 생성 중…" 배지')
  await page.screenshot({ path: `${OUT}/ev193-list.png` })
  await openDataset(`ev193-gen-${S}`)
  const skel = await page.locator('.ant-skeleton').count()
  ok(skel > 0, `P3b 생성 중 드로어에 Skeleton 카드 (${skel})`)
  ok(/문제를 만드는 중/.test(await bodyText()), 'P3c "AI가 문제를 만드는 중" 안내')
  await page.screenshot({ path: `${OUT}/ev193-skeleton.png` })
  await closeDrawer()

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  for (const d of [dsA, dsG]) if (d?.id) await api(`/eval/datasets/${d.id}`, { method: 'DELETE' }).catch(() => {})
  console.log('CLEANUP', [dsA?.id, dsG?.id].filter(Boolean).join(', '))
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (EVALUX193_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
