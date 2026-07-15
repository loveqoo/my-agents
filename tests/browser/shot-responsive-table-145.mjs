/* 스펙 145 e2e — 반응형 테이블(에이전트 리스트) 재보고 반영.
   144 사후 지적: "가로 스크롤 안전망"이 아니라 사용자가 원한 건 "다양한 가로 사이즈에서 표가
   반응형으로 잘 보이는 것"(모바일 최적화).

   1차 구현(minWidth:max-content 제거 + overflowWrap만)은 실측 결과 1024/820에서 여전히 overflow —
   원인: 고정폭 컬럼(소스104+준수96+버전110+공개130+상태100+액션96=636px) 합 + 나머지 유동 컬럼의
   min-content가 더해져 표의 intrinsic width가 약 890px에 고정, table-layout:auto라 컨테이너보다
   좁아지지 않음(1024/820 컨테이너 폭 742/538 < 890 → 진짜 가로 스크롤 발생, probe로 확인).

   2차 수정(공유 DataTable, admin/src/admin/shared.tsx) 반영:
   ① `<table style={tableLayout:'fixed'}>` — 컬럼이 컨테이너 폭을 강제로 나눠 가지므로(내용의
      min-content가 표를 늘리지 못함) intrinsic overflow 원천 차단, 내용은 그 폭 안에서 줄바꿈.
   ② 카드 스택 전환점 `screens.md`(768) → `screens.lg`(992)로 상향 — 9컬럼 표는 992 미만에서 이미
      비좁으므로(fixed로 각 컬럼이 너무 좁아짐) 그 구간은 카드 스택으로.
   ③ AgentsView 고정폭(width) 5개 제거(소스·준수·버전·공개·액션) — status(100)만 남음, tableLayout:
      fixed 하에서 나머지 컬럼은 자동 분배.

   에이전트 리스트 컬럼 9개(코드 확인, admin/src/admin/views/AgentsView.tsx ~1508행):
   에이전트·소스·준수·프롬프트·MCP·버전·공개·상태·(액션, title 없음이나 th 자체는 렌더).

   폭별 판정(수정 반영, screens.lg 브레이크포인트=992 기준):
   - 1400/1024(≥992=lg true): 데스크톱 표 — 래퍼 가로 스크롤 0(scrollWidth==clientWidth ±2px),
     thead th 9개 유지.
   - 820/600/390(<992=lg false): 카드 스택 — table 없음 + 카드형 레이아웃(라벨:값 행) + 문서 가로
     스크롤 0. (820은 1차 구현 때는 표였으나 2차 수정으로 전환점이 992로 올라가 카드가 됨 — 실측으로
     확정.)

   회귀(R6, 공유 컴포넌트 변경이라 다른 화면도 확인): 1400px에서 세션 메뉴 표 + 평가 메뉴 "실행 이력"
   탭 표도 정상 렌더 + 가로 스크롤 0.

   템플릿=shot-agents-ux-144.mjs(로그인·에이전트 메뉴 셀렉터 관례, antd Icon aria-label이 텍스트에
   합쳐지는 함정은 이 스펙엔 해당 상호작용 없어 미적용) + shot-eval-matrix-141.mjs(평가 메뉴 진입·
   탭 클릭 관례 — getByRole('tab', { name: ... })).

   앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-responsive-table-145.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_WIDE = '/tmp/table-145-wide.png'
const OUT_MID = '/tmp/table-145-mid.png'
const OUT_MOBILE = '/tmp/table-145-mobile.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const EXPECTED_TH = 9

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

/* DataTable은 <Panel><div overflowX:auto><table>...</table></div></Panel> 구조 — 표의 부모 div가
   가로 스크롤 래퍼. 없으면(카드 스택 모드) null. scope 생략 시 page 전체에서 첫 table.
   주의(실측으로 발견): antd Tabs는 방문한 탭 패널을 언마운트 안 하고 DOM에 남긴다(aria-hidden만) —
   탭이 있는 화면(평가)에서 무스코프 table.first()는 숨은 이전 탭의 table(크기 0)을 집어 거짓 통과를
   만든다. 반드시 활성 tabpanel로 스코프해야 한다. */
async function tableWrapMetrics(scope = page) {
  const tbl = scope.locator('table').first()
  if ((await tbl.count()) === 0) return null
  return await tbl.evaluate((el) => {
    const wrap = el.parentElement
    return { scrollWidth: wrap.scrollWidth, clientWidth: wrap.clientWidth }
  })
}

async function thCount() {
  return await page.locator('table thead th').count()
}

/** 데스크톱 표 판정: 표 존재 + 래퍼 가로 스크롤 0(±2px) + th 개수 유지. */
async function checkDesktopTable(label) {
  const m = await tableWrapMetrics()
  const th = await thCount()
  if (!m) {
    check(false, `${label}: table 없음(카드 스택으로 렌더됨 — 이 폭에서 데스크톱 표 기대)`)
    return
  }
  const diff = Math.abs(m.scrollWidth - m.clientWidth)
  check(
    diff <= 2 && th === EXPECTED_TH,
    `${label}: scrollWidth=${m.scrollWidth} clientWidth=${m.clientWidth}(diff=${diff}) + th=${th}(기대 ${EXPECTED_TH})`
  )
}

/** 카드 스택 판정(screens.lg=992 미만): table 없음 + Panel 카드 라벨("소스") 존재 + 문서 가로 스크롤 0. */
async function checkCardStack(label) {
  const tblCount = await page.locator('table').count()
  const cardLabelCount = await page.getByText('소스', { exact: true }).count()
  const docMetrics = await page.evaluate(() => ({
    scrollWidth: document.scrollingElement.scrollWidth,
    clientWidth: document.scrollingElement.clientWidth,
  }))
  const docDiff = Math.abs(docMetrics.scrollWidth - docMetrics.clientWidth)
  check(
    tblCount === 0 && cardLabelCount > 0 && docDiff <= 2,
    `${label}: table 없음(${tblCount === 0}) + 카드 라벨"소스" ${cardLabelCount}건 + 문서 가로 스크롤 diff=${docDiff}(scrollWidth=${docMetrics.scrollWidth} clientWidth=${docMetrics.clientWidth})`
  )
}

async function gotoAgents() {
  await page.getByRole('menuitem', { name: '에이전트' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- R1: 1400×1000 ----------
  await page.setViewportSize({ width: 1400, height: 1000 })
  await page.waitForTimeout(400)
  await checkDesktopTable('R1(1400×1000)')
  await page.screenshot({ path: OUT_WIDE, fullPage: true }).catch(() => {})
  console.log('shot:', OUT_WIDE)

  // ---------- R2: 1024×900 ----------
  await page.setViewportSize({ width: 1024, height: 900 })
  await page.waitForTimeout(400)
  await checkDesktopTable('R2(1024×900)')

  // ---------- R3: 820×900(2차 수정 — 카드 스택 전환점 lg=992로 상향, 820<992 → 카드 기대) ----------
  await page.setViewportSize({ width: 820, height: 900 })
  await page.waitForTimeout(400)
  await checkCardStack('R3(820×900)')
  await page.screenshot({ path: OUT_MID, fullPage: true }).catch(() => {})
  console.log('shot:', OUT_MID)

  // ---------- R4: 600×900(<992 → 카드 스택) ----------
  await page.setViewportSize({ width: 600, height: 900 })
  await page.waitForTimeout(400)
  await checkCardStack('R4(600×900)')

  // ---------- R5: 390×844(모바일, <992 → 카드 스택) ----------
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(400)
  await checkCardStack('R5(390×844)')
  await page.screenshot({ path: OUT_MOBILE, fullPage: true }).catch(() => {})
  console.log('shot:', OUT_MOBILE)

  // ---------- R6: 회귀(공유 컴포넌트) — 1400px에서 세션·평가(실행 이력) 표 ----------
  await page.setViewportSize({ width: 1400, height: 1000 })
  await page.waitForTimeout(400)

  await page.getByRole('menuitem', { name: '세션' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '세션' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)
  {
    const m = await tableWrapMetrics()
    if (!m) {
      check(false, 'R6a(세션, 1400): table 없음')
    } else {
      const diff = Math.abs(m.scrollWidth - m.clientWidth)
      check(diff <= 2, `R6a(세션, 1400): scrollWidth=${m.scrollWidth} clientWidth=${m.clientWidth}(diff=${diff})`)
    }
  }

  await page.getByRole('menuitem', { name: '평가' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '평가' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)
  await page.getByRole('tab', { name: '실행 이력' }).click()
  await page.waitForTimeout(500)
  {
    // 활성 tabpanel로 스코프(위 주의사항 — 무스코프 시 숨은 "문제집" 탭의 table을 오검출).
    const m = await tableWrapMetrics(page.getByRole('tabpanel'))
    if (!m) {
      check(false, 'R6b(평가·실행 이력, 1400): table 없음')
    } else {
      const diff = Math.abs(m.scrollWidth - m.clientWidth)
      check(diff <= 2, `R6b(평가·실행 이력, 1400): scrollWidth=${m.scrollWidth} clientWidth=${m.clientWidth}(diff=${diff})`)
    }
  }

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await page.screenshot({ path: OUT_MOBILE, fullPage: true }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
