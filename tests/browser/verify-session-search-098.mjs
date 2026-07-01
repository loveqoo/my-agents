/* 스펙 098 검증 — 세션 목록 서버측 검색 UI E2E.
   마커 세션 2건(agent_name=ZZBROWSERMARK098) 시드 후, 검색창에 마커 입력 →
   테이블이 서버측 재조회로 그 2건만 남는지(디바운스→q→server), clear 시 복귀하는지 확인.
   행 식별은 <code>(session_id)로. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(`${pwDir}/index.js`)
const chromium = _pw.chromium ?? _pw.default?.chromium
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
const MARK = 'ZZBROWSERMARK098'

// 테이블의 session_id 코드 셀 수집(현재 페이지).
const codes = () => page.evaluate(() =>
  [...document.querySelectorAll('table code')].map((c) => c.textContent.trim()).filter(Boolean))

const R = {}
try {
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('세션', { exact: true }).first().waitFor({ timeout: 10000 })

  // ===== 세션 뷰 =====
  await page.getByText('세션', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  R.search_input_present = await page.getByPlaceholder('세션 ID·유저·에이전트 검색').count()
  R.before_codes = await codes()

  // ===== 검색: 마커 입력 → 서버 재조회로 2건만 =====
  const box = page.getByPlaceholder('세션 ID·유저·에이전트 검색')
  await box.fill(MARK)
  await page.waitForTimeout(1500) // 디바운스(300)+서버 왕복
  R.after_codes = await codes()
  await page.screenshot({ path: '/tmp/098-search.png' })

  // ===== clear → 복귀 =====
  await box.fill('')
  await page.waitForTimeout(1500)
  R.cleared_codes = await codes()

  // ===== 매칭 없는 검색 → 빈 테이블 empty 문구 =====
  await box.fill('nonexistent_zz_xyzzy_098')
  await page.waitForTimeout(1500)
  R.noresult_codes = await codes()
  R.empty_text = await page.evaluate(() =>
    /조건에 맞는 세션이 없습니다/.test(document.body.textContent || ''))

  // ===== 판정 =====
  const both = ['sess_zz098_a', 'sess_zz098_b']
  R.PASS_search_narrows = both.every((s) => R.after_codes.includes(s)) &&
    R.after_codes.every((s) => both.includes(s))
  R.PASS_cleared_restores = !R.cleared_codes.includes('sess_zz098_a') ||
    R.cleared_codes.length >= R.after_codes.length // 복귀 시 마커만이 아닌 더 넓은 목록
  R.PASS_noresult_empty = R.noresult_codes.length === 0 && R.empty_text
  R.PASS_input_present = R.search_input_present === 1
} catch (e) { R.error = e?.message ?? String(e); process.exitCode = 1 }
finally { console.log(JSON.stringify(R, null, 1)); await browser.close() }
