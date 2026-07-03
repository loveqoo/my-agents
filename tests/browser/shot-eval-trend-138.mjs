/* 스펙 138 e2e — 평가 2탄: 성적 추이(TrendChart) + 런 비교(CompareDrawer), 결정적 회귀 유발.
   문제집 생성 → 문제 추가(기본 2기준) → 옵시디언 매니저로 시험 실행[런A] → 문제집 드로어 재오픈 →
   "성적 추이" 섹션(런 1개) 확인 → 케이스에 "답변에 포함"(output_contains, 불가능 문자열) 기준 추가 →
   같은 에이전트로 재실행[런B, 결정적 0%] → 추이 차트(점 2개·마지막 라벨 0%) 확인 → 실행 이력 탭
   문제집 필터 → 런 2개 체크·비교 → 비교 드로어(회귀 태그·assert diff) 확인 → 정리(삭제).

   assert diff의 output_contains 기준은 런A 이후 새로 추가됐다 — "기존 기준이 깨짐"(새로 실패, red)이
   아니라 "런A에 없던 기준이 B에서 실패"라 별도 orange 태그 "신규 기준 · 실패"로 판정한다
   (코디네이터 반영, EvalTrend.tsx:191-193 — 최초 e2e에서 "새로 실패" 기대가 틀렸음을 T7이 잡아냄).

   템플릿=shot-eval-137.mjs(로그인·평가 메뉴·문제집/케이스 생성·실행·폴링 재사용, antd 6 셀렉터
   주의사항 동일 적용 — .ant-select 사용·getByRole('tabpanel')로 활성 탭 스코프 고정·드로어는
   Escape로 닫아 마스크(zIndex 1000)가 아래 클릭을 가로채지 않게 함).

   앱 코드 수정 없음 — 검증 전용. 실행 2회 모두 real LLM 호출이 있어 각 최대 180초 폴링한다.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-eval-trend-138.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_TREND = '/tmp/eval-138-trend.png'
const OUT_COMPARE = '/tmp/eval-138-compare.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-138-회귀시험'
const CASE_NAME = '회귀 케이스'
const QUESTION = 'A/B 테스트에서 중요한 것은?'
const AGENT = '옵시디언 매니저'
const BAD_ARG = '절대안나올문자열XYZ987'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

// antd Tabs는 방문한 탭 패널을 언마운트하지 않고 aria-hidden으로만 감춘다 — getByRole('tabpanel')은
// Playwright 접근성 트리 필터로 aria-hidden=true 패널을 자동 제외하므로 활성 탭 범위로 고정한다.
const activePanel = () => page.getByRole('tabpanel')
const dsRow = () => activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })
const runRows = () => activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })

async function closeDrawer() {
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}

async function openDatasetTab() {
  await page.getByRole('tab', { name: '문제집' }).click()
  await page.waitForTimeout(400)
}

async function openRunsTab() {
  await page.getByRole('tab', { name: '실행 이력' }).click()
  await page.waitForTimeout(400)
}

/** rows(활성 탭 내 DATASET_NAME 행들)의 innerText 중 pattern에 매치하는 게 하나라도 생길 때까지 폴링. */
async function pollFor(pattern, label, deadlineMs = 180000) {
  const deadline = Date.now() + deadlineMs
  let lastTexts = []
  while (Date.now() < deadline) {
    lastTexts = await runRows().allInnerTexts().catch(() => [])
    if (lastTexts.some((t) => pattern.test(t))) return { ok: true, texts: lastTexts }
    await page.waitForTimeout(5000)
    await page.getByRole('button', { name: '새로고침' }).click().catch(() => {})
    await page.waitForTimeout(300)
  }
  return { ok: false, texts: lastTexts }
}

try {
  // ---------- 로그인 → 평가 메뉴 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })

  await page.getByText('평가', { exact: true }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '평가' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)

  // ---------- 사전 정리(멱등화): 이전 실행 잔여 "e2e-138" 문제집이 있으면 먼저 삭제 ----------
  let preExisting = await dsRow().count()
  while (preExisting > 0) {
    await dsRow().first().getByRole('button').click()
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: '삭제' }).click()
    await page.waitForTimeout(600)
    preExisting = await dsRow().count()
  }
  console.log(`(사전정리) 잔여 "${DATASET_NAME}" 문제집 제거 완료(count=${preExisting})`)

  // ---------- 문제집 생성 ----------
  await page.getByRole('button', { name: '새 문제집' }).click()
  await page.getByRole('dialog').getByText('새 문제집', { exact: true }).waitFor({ timeout: 5000 })
  await page.getByPlaceholder('이름 (예: 옵시디언 매니저 회귀 시험)').fill(DATASET_NAME)
  await page.getByRole('button', { name: '만들기' }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(500)
  const dsCount = await dsRow().count()
  console.log(`(setup) 문제집 목록에 "${DATASET_NAME}" 행 (count=${dsCount})`)

  // ---------- 문제 추가(기본 2기준 그대로) ----------
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.getByRole('button', { name: '문제 추가' }).click()
  await page.waitForTimeout(300)
  await page.getByPlaceholder('문제 이름 (예: RAG 필수 회귀)').fill(CASE_NAME)
  await page.getByPlaceholder('에이전트에게 보낼 질문').fill(QUESTION)
  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)
  const setupDrawerText = await page.locator('#root').innerText().catch(() => '')
  console.log(`(setup) 케이스 카드 "2개 기준" 존재: ${/2개 기준/.test(setupDrawerText)}`)

  // ---------- 에이전트 선택 → 시험 실행 [런 A] ----------
  const agentSelect = () =>
    page.locator('.ant-select').filter({ hasText: '시험 칠 에이전트 선택' }).or(page.locator('.ant-select').filter({ hasText: AGENT }))
  await agentSelect().first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: AGENT }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '시험 실행' }).click()
  await page.getByText('시험 실행 시작', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  await page.getByRole('tab', { name: '실행 이력', selected: true }).waitFor({ timeout: 8000 }).catch(() => {})
  await closeDrawer()

  const runA = await pollFor(/ok/, '런A(ok)')
  const runAok = runA.texts.some((t) => /ok/.test(t) && /100% \(1\/1\)/.test(t))
  check(runAok, `[사전] 런A ok+100% (1/1) (텍스트=${JSON.stringify(runA.texts)})`)

  // ---------- 문제집 탭 → 드로어 재오픈 → T1: 성적 추이 섹션(런 1개) ----------
  await openDatasetTab()
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(600)
  const t1Text = await page.locator('#root').innerText().catch(() => '')
  const t1HasTitle = /성적 추이/.test(t1Text)
  const t1HasHint = /런이 2개 이상이면 추이/.test(t1Text)
  const t1HasRow = /100% \(1\/1\)/.test(t1Text)
  check(t1HasTitle && (t1HasHint || t1HasRow), `T1: "성적 추이" 섹션(${t1HasTitle}) + ("런이 2개 이상" 문구(${t1HasHint}) 또는 100% 행(${t1HasRow}))`)

  // ---------- 케이스 편집: "답변에 포함"(output_contains) 기준 추가 ----------
  const caseCard = page.locator('div').filter({ hasText: CASE_NAME }).filter({ hasText: '기준' }).last()
  await caseCard.getByRole('button').first().click() // 편집(연필) 아이콘 — 카드의 첫 버튼
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '채점 기준 추가' }).click()
  await page.waitForTimeout(200)
  const newAssertSelect = page.locator('.ant-select').filter({ hasText: '필수 도구/노드' })
  await newAssertSelect.waitFor({ timeout: 5000 })
  await newAssertSelect.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: '답변에 포함' }).first().click()
  await page.waitForTimeout(200)
  const argInput = page.getByPlaceholder('답변에 이 문구가 있어야 통과')
  await argInput.waitFor({ timeout: 5000 })
  await argInput.fill(BAD_ARG)
  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)
  const editedText = await page.locator('#root').innerText().catch(() => '')
  console.log(`(setup) 편집 후 "3개 기준"+"output_contains:${BAD_ARG}" 존재: ${/3개 기준/.test(editedText)} / ${editedText.includes(`output_contains: ${BAD_ARG}`) || editedText.includes(`output_contains:${BAD_ARG}`)}`)

  // ---------- 같은 에이전트로 재실행 [런 B, 결정적 0%] ----------
  await agentSelect().first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: AGENT }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '시험 실행' }).click()
  await page.getByText('시험 실행 시작', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  await page.getByRole('tab', { name: '실행 이력', selected: true }).waitFor({ timeout: 8000 }).catch(() => {})
  await closeDrawer()

  const runB = await pollFor(/0% \(0\/1\)/, '런B(0%)')
  const runBok = runB.texts.some((t) => /ok/.test(t) && /0% \(0\/1\)/.test(t))
  check(runBok, `[사전] 런B ok+0% (0/1) (텍스트=${JSON.stringify(runB.texts)})`)

  // ---------- T2: 문제집 드로어 재오픈 → 추이 SVG(점 2개, 마지막 라벨 0%) + 목록 2행 ----------
  await openDatasetTab()
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(700)
  const svg = page.locator('svg[aria-label="성적 추이"]')
  const svgVisible = await svg.isVisible().catch(() => false)
  const pointCount = svgVisible ? await svg.locator('circle[r="4"]').count() : 0
  const svgTexts = svgVisible
    ? await svg.evaluate((el) => Array.from(el.querySelectorAll('text')).map((t) => t.textContent))
    : []
  const hasZeroLabel = svgTexts.includes('0%')
  const t2Text = await page.locator('#root').innerText().catch(() => '')
  const t2ListHas100 = /100% \(1\/1\)/.test(t2Text)
  const t2ListHas0 = /0% \(0\/1\)/.test(t2Text)
  check(
    svgVisible && pointCount === 2 && hasZeroLabel && t2ListHas100 && t2ListHas0,
    `T2: SVG 표시(${svgVisible})·점 2개(count=${pointCount})·마지막 라벨"0%"(${hasZeroLabel})·목록 100%행(${t2ListHas100})·0%행(${t2ListHas0}) [svgTexts=${JSON.stringify(svgTexts)}]`
  )
  // 사용자 UI/UX 확인용 스샷 — 추이 차트가 보이는 드로어 상태.
  await page.screenshot({ path: OUT_TREND, fullPage: true }).catch(() => {})
  console.log('shot:', OUT_TREND)

  // ---------- 실행 이력 탭 → T3: 문제집 필터 → 2행만 ----------
  await closeDrawer()
  await openRunsTab()
  const filterSelect = page.locator('.ant-select').filter({ hasText: '문제집으로 필터' })
  await filterSelect.click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: DATASET_NAME }).first().click()
  await page.waitForTimeout(500)
  const filteredCount = await runRows().count()
  check(filteredCount === 2, `T3: "문제집으로 필터"(${DATASET_NAME}) 적용 후 행 2개 (count=${filteredCount})`)

  // ---------- T4: 두 런 체크 → "선택 2/2 비교" 활성 → 클릭 ----------
  await runRows().nth(0).getByRole('checkbox').click()
  await page.waitForTimeout(200)
  await runRows().nth(1).getByRole('checkbox').click()
  await page.waitForTimeout(200)
  const cmpBtn = page.getByRole('button', { name: '선택 2/2 비교' })
  const cmpBtnVisible = await cmpBtn.isVisible().catch(() => false)
  const cmpBtnEnabled = cmpBtnVisible && (await cmpBtn.isEnabled().catch(() => false))
  check(cmpBtnVisible && cmpBtnEnabled, `T4: "선택 2/2 비교" 버튼 표시(${cmpBtnVisible})·활성(${cmpBtnEnabled})`)
  await cmpBtn.click()
  await page.getByText('런 비교 (이전 → 이후)', { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(600)

  // ---------- T5: 요약(100% → 0%, -100%p red 태그, 회귀 1건 Alert) ----------
  const cmpText = await page.locator('#root').innerText().catch(() => '')
  const t5aScore = /100%\s*→\s*0%/.test(cmpText)
  const t5bDelta = /-100%p/.test(cmpText)
  const t5cAlert = /회귀 1건/.test(cmpText)
  check(t5aScore && t5bDelta && t5cAlert, `T5: "100% → 0%"(${t5aScore})·"-100%p" red 태그(${t5bDelta})·"회귀 1건" Alert(${t5cAlert})`)

  // ---------- T6: 케이스 행에 "회귀" 태그 + 이전 "통과"/이후 "실패" ----------
  const nameSpan = page.getByText(CASE_NAME, { exact: true })
  const caseRowClickable = nameSpan.locator('xpath=..')
  const caseRowText = await caseRowClickable.innerText().catch(() => '')
  const t6HasRegressTag = /회귀/.test(caseRowText)
  const t6HasPrevPass = /이전[\s\S]*통과/.test(caseRowText)
  const t6HasNextFail = /이후[\s\S]*실패/.test(caseRowText)
  check(t6HasRegressTag && t6HasPrevPass && t6HasNextFail, `T6: 케이스 행 "회귀" 태그(${t6HasRegressTag})·이전"통과"(${t6HasPrevPass})·이후"실패"(${t6HasNextFail}) [행텍스트=${JSON.stringify(caseRowText)}]`)

  // ---------- T7: 행 클릭(펼침) → assert diff에 output_contains 행 + "신규 기준 · 실패" 태그(orange) ----------
  // 런 A 이후 새로 추가된 기준이 B에서 실패 — "기존 기준이 깨짐"(새로 실패, red)과 구분되는
  // 세 번째 상태 라벨(코디네이터 반영, EvalTrend.tsx:191-193).
  await caseRowClickable.click()
  await page.waitForTimeout(400)
  const caseOuter = nameSpan.locator('xpath=../..')
  const caseOuterText = await caseOuter.innerText().catch(() => '')
  const assertLine = `output_contains:${BAD_ARG}`
  const t7HasAssertRow = caseOuterText.includes(assertLine)
  const t7HasNewCriterionTag = /신규 기준\s*·\s*실패/.test(caseOuterText)
  check(t7HasAssertRow && t7HasNewCriterionTag, `T7: assert diff에 "${assertLine}" 행(${t7HasAssertRow}) + "신규 기준 · 실패" 태그(${t7HasNewCriterionTag}) [펼침텍스트=${JSON.stringify(caseOuterText)}]`)

  // 사용자 UI/UX 확인용 스샷 — 비교 드로어 펼침 상태.
  await page.screenshot({ path: OUT_COMPARE, fullPage: true }).catch(() => {})
  console.log('shot:', OUT_COMPARE)

  // ---------- 정리: 비교 드로어 닫고 문제집 삭제 → T8 ----------
  await closeDrawer()
  await openDatasetTab()
  await page.waitForTimeout(300)
  await dsRow().first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
  const remaining = await dsRow().count()
  check(remaining === 0, `T8: 정리 — 목록에서 "${DATASET_NAME}" 사라짐(잔여 행=${remaining})`)

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await page.screenshot({ path: OUT_COMPARE, fullPage: true }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
