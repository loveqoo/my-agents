/* 스펙 125 검증 — 메모리 "조회 시험" 드로어에 **지속 진단 패널**이 뜨는지.
   회상 후(결과·0건·오류 무관) "진단" 접이식이 남아 백엔드 상태·임베딩 모델·스코프·오류를 보인다
   (사라지는 토스트 아님). 시스템 Chrome.
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-memory-search-diag-125.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/memory-search-diag-125.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1200, height: 1100 } })
const page = await ctx.newPage()

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 메모리 뷰로
  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(800)

  // 유저 메모리 탭 — 유저는 항상 존재(진단 패널은 기억 유무 무관 렌더)
  await page.getByText('유저 메모리', { exact: true }).first().click()
  await page.waitForTimeout(600)
  // 유저 Select 열어 첫 유저 선택(showSearch — combobox 롤로 연다)
  const combo = page.getByRole('combobox').first()
  await combo.click({ timeout: 8000 })
  await page.waitForTimeout(500)
  await page.locator('.ant-select-item-option').first().click({ timeout: 8000 })
  await page.waitForTimeout(800)

  // "조회 시험" 버튼 → 드로어
  await page.getByRole('button', { name: /조회 시험/ }).first().click()
  await page.waitForTimeout(600)
  const drawerVisible = await page.getByText(/회상 시험|같은 메모리 코어/).first().isVisible().catch(() => false)
  check(drawerVisible, '회상 시험 드로어 열림')

  // 질의 입력 후 조회(드로어 내 primary 버튼 = 파란 "조회")
  await page.locator('.ant-drawer textarea').first().fill('내가 선호하는 보고서 형식은?')
  await page.locator('.ant-drawer button.ant-btn-primary').first().click({ timeout: 8000 })
  await page.waitForTimeout(1800)

  // 지속 진단 패널: "진단" 라벨이 드로어에 남아있나(토스트 아님)
  const diagLabel = page.locator('.ant-drawer').getByText('진단', { exact: false }).first()
  const diagVisible = await diagLabel.isVisible().catch(() => false)
  check(diagVisible, '지속 "진단" 패널이 드로어에 표시됨(사라지지 않음)')

  // 진단 펼쳐 내용 확인(오류면 이미 펼쳐짐; 아니면 클릭)
  await diagLabel.click().catch(() => {})
  await page.waitForTimeout(400)
  const body = await page.locator('.ant-drawer').innerText().catch(() => '')
  check(/임베딩 모델|백엔드|스코프/.test(body), '진단 내용(임베딩 모델·백엔드·스코프) 노출')
  // 비밀 누출 0 — 화면에 api_key/sk- 흔적 없어야
  check(!/sk-[A-Za-z0-9]{6,}/.test(body), '비밀(sk-…) 화면 노출 없음')

  await page.screenshot({ path: OUT, fullPage: false })
  console.log('shot:', OUT)
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
