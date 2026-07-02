/* 스펙 129 검증 — 세션 상세 드로어 "세션 종료" 버튼 배선(admin/src/admin/views/SessionsView.tsx).
   시스템 Chrome.

   사전 시드(bash, 이 스크립트 실행 전에 별도로 수행 — 실 세션을 절대 종료하지 않는다):
   - sessions 테이블에 검증용 세션 1건: session_id='sess_v129end', status='active',
     channel='playground', agent_pk=(기존 agents 1건 재사용), user_id=NULL.
   - 멱등화를 위해 INSERT 전 session_id='sess_v129end' 행을 DELETE.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-session-end-129.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/session-end-129.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const SEED_ID = 'sess_v129end'

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

  // 1: 로그인 → "세션" 메뉴 → 검색 Input에 seed id 입력 → 1초 대기 → "일치 1건" 표시.
  await page.getByText('세션', { exact: true }).first().click()
  await page.waitForTimeout(800)
  const search = page.getByPlaceholder('세션 ID·유저·에이전트 검색')
  await search.fill(SEED_ID)
  await page.waitForTimeout(1000)
  const bodyText1 = await page.locator('#root').innerText().catch(() => '')
  check(/일치 1건/.test(bodyText1), `1: 검색 "${SEED_ID}" → "일치 1건" 표시`)

  // 2: 그 행 클릭 → 드로어 열림(제목에 seed id) + "세션 종료" 버튼 존재.
  // 이 화면 드로어는 커스텀 컴포넌트(admin/src/admin/shared.tsx Drawer — antd Drawer 아님,
  // .ant-drawer-* 클래스 없음)라 page 레벨 셀렉터로 확인한다. 제목 span은 목록 행의 <code>
  // 텍스트와 값이 같아 count()==2(행 + 드로어 제목)로 열림을 판정한다.
  const row = page.locator('tr', { hasText: SEED_ID }).first()
  const rowVisible = await row.isVisible().catch(() => false)
  check(rowVisible, '2: 목록에 시드 행 존재')
  if (rowVisible) await row.click({ timeout: 8000 })
  await page.waitForTimeout(500)
  const seedTextCount = await page.getByText(SEED_ID, { exact: true }).count().catch(() => 0)
  check(seedTextCount >= 2, `2: 드로어 열림(제목에 "${SEED_ID}", 화면 내 일치 ${seedTextCount}건 — 행+드로어 제목)`)
  const endBtn = page.getByRole('button', { name: '세션 종료' })
  const endBtnVisible = await endBtn.isVisible().catch(() => false)
  check(endBtnVisible, '2: "세션 종료" 버튼 존재')

  // 3: "세션 종료" 클릭 → Popconfirm("이 세션을 종료할까요?") 표시 → "종료" 클릭.
  if (endBtnVisible) await endBtn.click({ timeout: 8000 })
  await page.waitForTimeout(300)
  const popconfirmVisible = await page.getByText('이 세션을 종료할까요?').first().isVisible().catch(() => false)
  check(popconfirmVisible, '3: Popconfirm "이 세션을 종료할까요?" 표시')
  const confirmBtn = page.getByRole('button', { name: '종료', exact: true })
  const confirmBtnVisible = await confirmBtn.isVisible().catch(() => false)
  check(confirmBtnVisible, '3: Popconfirm "종료" 버튼 존재')
  if (confirmBtnVisible) await confirmBtn.click({ timeout: 8000 })

  // 4: 성공 토스트 또는 드로어 상태가 "완료"로 바뀜 + "세션 종료" 버튼이 사라짐(닫기만 남음).
  // 응답(네트워크 왕복) 대기 — waitFor로 실제 상태변화를 폴링(고정 짧은 대기 대신).
  const toastVisible = await page.getByText('세션을 종료했습니다').first().waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false)
  await page.waitForTimeout(500)
  const statusCompleted = await page.getByText('완료', { exact: true }).first().isVisible().catch(() => false)
  check(toastVisible || statusCompleted, `4: 성공 토스트(${toastVisible}) 또는 드로어 "완료" 표시(${statusCompleted})`)
  const endBtnGoneNow = await page.getByRole('button', { name: '세션 종료' }).isVisible().catch(() => false)
  check(!endBtnGoneNow, '4: "세션 종료" 버튼이 사라짐(닫기만 남음)')
  const closeOnlyVisible = await page.getByRole('button', { name: '닫기' }).isVisible().catch(() => false)
  check(closeOnlyVisible, '4: "닫기" 버튼은 남아있음')

  // 6(사전): 드로어 완료 상태 스크린샷(닫기 전에 캡처 — 완료 상태 증거).
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('shot:', OUT)

  // 5: 드로어 닫기 → 목록 재조회로 해당 행 status가 완료 계열로 표시(검색 유지 상태에서 확인).
  await page.getByRole('button', { name: '닫기' }).click({ timeout: 8000 })
  await page.waitForTimeout(1000)
  const rowAfter = page.locator('tr', { hasText: SEED_ID }).first()
  const rowAfterText = await rowAfter.innerText().catch(() => '')
  check(rowAfterText.includes('완료'), `5: 목록 재조회 후 시드 행 status "완료" 표시(실측 행: "${rowAfterText.replace(/\n/g, ' | ')}")`)
} catch (e) {
  console.error('ERR', e.message)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
