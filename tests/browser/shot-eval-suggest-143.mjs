/* 스펙 143 e2e — 평가 7탄: 에이전트 문제집 AI 출제(평가 도우미 1탄).
   문제집 "e2e-143-AI출제" 생성(agent 종류, 잔여 사전 삭제) → 드로어 열기 → K1: "AI로 문제
   채우기" 버튼 존재하되 비활성(에이전트 미선택) + 툴팁 "에이전트를 먼저 선택" 안내 → 에이전트
   "옵시디언 매니저" 선택 → K2: 버튼 활성화 → 클릭 → 성공 토스트("AI 출제 시작") → 백그라운드
   생성(LLM 다회 호출) 완료까지 최대 300초 폴링(설명이 "AI 출제 N건 추가"로 바뀔 때까지) →
   K3: N≥5 확인 → 드로어 다시 열기 → K4: "AI 출제 i (RAG)"/"AI 출제 i (역할)" 문제 카드 혼재 +
   RAG형 "trace_has: rag:" 태그 · 역할형 "llm_judge: ..." 태그 확인 → K5: 문제 하나를 편집(연필)해
   질문 텍스트 수정 → 저장 → 카드 반영 확인 → 스크린샷 → K6: 문제집 삭제 정리.

   템플릿=shot-eval-golden-142.mjs(로그인·문제집 생성·폴링·멱등 사전정리 재사용, antd 6 셀렉터
   주의사항 동일 적용 — .ant-select 사용·getByRole('tabpanel')로 활성 탭 스코프 고정·드로어는
   Escape로 닫아 마스크가 아래 클릭을 가로채지 않게 함). 142와 동일하게 이 프로젝트의 Drawer는
   antd Drawer가 아니라 자체 구현(shared/Drawer, position:fixed 오버레이 순수 div) —
   ant-drawer-* 클래스가 전혀 없어 카드는 인라인 style(`border: 1px solid
   var(--color-border-secondary)`) 문자열로 구조적으로 특정한다.

   문제집 목록(EvalView 최상위 state)은 EvalView 마운트 시 1회만 도는 loadDatasets()로만
   갱신되고(러너처럼 실행 중 폴링 useEffect가 없음 — 142 코드 확인과 동일), "문제집 탭 재클릭"이
   아니라 **다른 메뉴로 이동 후 평가로 복귀**(컴포넌트 리마운트 → loadDatasets 재호출)로 새로고침
   한다. 반면 드로어 안 문제(cases) 목록은 dataset prop이 null→object로 바뀔 때(드로어 닫았다
   다시 열 때) load() 콜백이 재생성되어 다시 불러온다 — 지시된 "드로어는 닫았다 다시 열면 문제
   갱신"과 일치(코드: DatasetDrawer의 load useCallback deps=[dataset?.id], 드로어 close 시
   부모가 setDetail(null)로 dataset을 null로 만들었다가 재오픈 시 다시 값이 들어와 deps가
   바뀌므로 재실행됨).

   앱 코드 수정 없음 — 검증 전용. 실행은 하지 않는다(출제·편집 흐름만 확인 — 시험 실행 검증은
   verify_143_suggest.py의 S4가 이미 커버).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-eval-suggest-143.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/eval-143-suggest.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-143-AI출제'
const AGENT = '옵시디언 매니저'

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
const cardLoc = () => page.locator('div[style*="border: 1px solid var(--color-border-secondary)"]').filter({ hasText: '개 기준' })

async function closeDrawer() {
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}

async function gotoEval() {
  await page.getByRole('menuitem', { name: '평가' }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '평가' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

async function openDrawer() {
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(400)
}

/** 문제집 탭: dsRow의 description이 predicate를 만족할 때까지 폴링 — 142 템플릿과 동일하게
    "다른 메뉴로 이동 후 평가로 복귀"로 EvalView를 리마운트해 loadDatasets()를 재호출한다. */
async function pollDatasetDesc(predicate, deadlineMs = 300000) {
  const deadline = Date.now() + deadlineMs
  let lastTexts = []
  while (Date.now() < deadline) {
    lastTexts = await dsRow().allInnerTexts().catch(() => [])
    if (lastTexts.some(predicate)) return { ok: true, texts: lastTexts }
    await page.waitForTimeout(3000)
    await page.getByRole('menuitem', { name: '에이전트' }).first().click()
    await page.waitForTimeout(300)
    await gotoEval()
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

  await gotoEval()

  // ---------- 사전 정리(멱등화): 이전 실행 잔여 "e2e-143-AI출제" 문제집이 있으면 먼저 삭제 ----------
  let preExisting = await dsRow().count()
  while (preExisting > 0) {
    await dsRow().first().getByRole('button').click()
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: '삭제' }).click()
    await page.waitForTimeout(600)
    preExisting = await dsRow().count()
  }
  console.log(`(사전정리) 잔여 "${DATASET_NAME}" 문제집 제거 완료(count=${preExisting})`)

  // ---------- 문제집 생성(agent 종류 — 기본값) ----------
  await page.getByRole('button', { name: '새 문제집' }).click()
  await page.getByRole('dialog').getByText('새 문제집', { exact: true }).waitFor({ timeout: 5000 })
  await page.getByPlaceholder('이름 (예: 옵시디언 매니저 회귀 시험)').fill(DATASET_NAME)
  await page.getByRole('button', { name: '만들기' }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(500)
  const dsCount = await dsRow().count()
  console.log(`(setup) 문제집 목록에 "${DATASET_NAME}" 행 (count=${dsCount})`)

  // ---------- 드로어 열기 ----------
  await openDrawer()

  // ---------- K1: "AI로 문제 채우기" 버튼 존재하되 비활성(에이전트 미선택) + 툴팁 안내 ----------
  const suggestBtn = () => page.getByRole('button', { name: 'AI로 문제 채우기' })
  const k1Visible = await suggestBtn().isVisible().catch(() => false)
  const k1Disabled = await suggestBtn().isDisabled().catch(() => false)
  // Playwright locator.hover()는 disabled 버튼도 동작한다(hover 액션성 체크는 "enabled" 불요구 —
  // click과 다름).
  await suggestBtn().hover().catch(() => {})
  await page.waitForTimeout(500)
  // antd 6은 툴팁 텍스트 컨테이너 클래스를 ant-tooltip-inner → ant-tooltip-container로 바꿨다
  // (실측 DOM 확인: <div class="ant-tooltip-container" role="tooltip">...) — role 셀렉터로 버전 무관하게 고정.
  const tooltipText1 = (await page.locator('[role="tooltip"]').first().innerText().catch(() => '')) ?? ''
  const k1TooltipOk = tooltipText1.includes('에이전트를 먼저 선택')
  check(
    k1Visible && k1Disabled && k1TooltipOk,
    `K1: 버튼 표시(${k1Visible}) + 비활성(${k1Disabled}) + 툴팁 "에이전트를 먼저 선택" 안내(${k1TooltipOk}) [툴팁="${tooltipText1}"]`
  )

  // ---------- 에이전트 "옵시디언 매니저" 선택 ----------
  await page.locator('.ant-select').filter({ hasText: '시험 칠 에이전트 선택' }).click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: AGENT }).first().click()
  await page.waitForTimeout(300)

  // ---------- K2: 버튼 활성화 → 클릭 → 성공 토스트 "AI 출제 시작" ----------
  const k2Enabled = !(await suggestBtn().isDisabled().catch(() => true))
  await suggestBtn().click()
  await page.locator('.ant-message-notice').first().waitFor({ timeout: 8000 }).catch(() => {})
  const toastText = (await page.locator('.ant-message-notice').first().textContent().catch(() => '')) ?? ''
  const k2Toast = toastText.includes('AI 출제 시작')
  check(k2Enabled && k2Toast, `K2: 에이전트 선택 후 버튼 활성(${k2Enabled}) + 성공 토스트 "AI 출제 시작"(${k2Toast}) [토스트="${toastText}"]`)

  await closeDrawer()

  // ---------- 폴링(최대 300초): 목록 설명이 "AI 출제 N건 추가"로 바뀔 때까지 ----------
  const genRe = /AI 출제 (\d+)건 추가/
  const gen = await pollDatasetDesc((t) => genRe.test(t), 300000)
  const genMatch = gen.texts.find((t) => genRe.test(t))
  const madeCount = genMatch ? parseInt(genRe.exec(genMatch)[1], 10) : 0

  // ---------- K3: 설명 "AI 출제 N건 추가"(N≥5) ----------
  check(gen.ok && madeCount >= 5, `K3: 설명 "AI 출제 N건 추가"(N≥5) — N=${madeCount} (텍스트=${JSON.stringify(gen.texts)})`)

  // ---------- 드로어 다시 열기 ----------
  await openDrawer()

  // ---------- K4: "AI 출제 i (RAG)"/"AI 출제 i (역할)" 문제 카드 혼재 + 태그 ----------
  const cardTexts = await cardLoc().allInnerTexts().catch(() => [])
  const ragCards = cardTexts.filter((t) => /AI 출제 \d+ \(RAG\)/.test(t) && t.includes('trace_has: rag:'))
  const personaCards = cardTexts.filter((t) => /AI 출제 \d+ \(역할\)/.test(t) && t.includes('llm_judge:'))
  const k4 = ragCards.length > 0 && personaCards.length > 0
  check(
    k4,
    `K4: RAG형 카드(${ragCards.length}건, "trace_has: rag:" 태그) + 역할형 카드(${personaCards.length}건, "llm_judge:" 태그) 혼재(${k4})`
  )
  if (!k4) console.log('카드 텍스트=', JSON.stringify(cardTexts))

  // ---------- K5: 문제 하나를 편집(연필) → 질문 텍스트 수정 → 저장 → 카드에 반영 ----------
  const editTarget = cardLoc().first()
  await editTarget.getByRole('button').first().click()
  await page.waitForTimeout(300)
  const qInput = page.getByPlaceholder('에이전트에게 보낼 질문')
  await qInput.waitFor({ timeout: 5000 })
  const beforeQuestion = await qInput.inputValue()
  const newQuestion = `${beforeQuestion} (e2e-143 수정)`
  await qInput.fill(newQuestion)
  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)
  const afterTexts = await cardLoc().allInnerTexts().catch(() => [])
  const k5 = afterTexts.some((t) => t.includes(newQuestion))
  check(k5, `K5: 편집 저장 → 카드에 수정된 질문 반영(${k5}) [질문="${newQuestion}"]`)

  // 사용자 UI/UX 확인용 스샷 — 혼합 문제 카드들이 보이는 드로어 상태.
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)

  // ---------- 정리: 드로어 닫고 문제집 삭제 → K6 ----------
  await closeDrawer()
  await dsRow().first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
  const remaining = await dsRow().count()
  check(remaining === 0, `K6: 정리 — 목록에서 "${DATASET_NAME}" 사라짐(잔여 행=${remaining})`)

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
