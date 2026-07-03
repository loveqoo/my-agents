/* 스펙 139 e2e — 평가 3탄: LLM-judge(비결정) 채점 축.
   문제집 생성 → 문제 추가(기본 2기준 유지 + "채점 기준 추가"로 AI 판정(llm_judge) 기준 삽입) →
   케이스 카드에 "3개 기준"+purple llm_judge 태그(T/E1) → 옵시디언 매니저로 시험 실행(real LLM 턴+심판
   호출이라 최대 180초 폴링) → 실행 이력 100%(1/1)(E2) → 성적표 드로어에서 케이스 통과 +
   assert 상세에 llm_judge 행 초록 체크(E3) → "관측" 펼침에서 AI 판정 purple 태그+PASS green 태그+
   기준 문장+판정 이유 문장(E4) → 스크린샷 → 문제집 삭제 정리(E5).

   템플릿=shot-eval-trend-138.mjs(로그인·평가 메뉴·문제집/케이스 생성·실행·폴링·멱등 사전정리 재사용,
   antd 6 셀렉터 주의사항 동일 적용 — .ant-select 사용·getByRole('tabpanel')로 활성 탭 스코프 고정·
   드로어는 Escape로 닫아 마스크가 아래 클릭을 가로채지 않게 함·"div 필터 후 .last()"로 최내부
   컨테이너 특정).

   앱 코드 수정 없음 — 검증 전용. 심판 기준은 verify_139(J4a)와 동일한 "답변이 한국어로 작성되었는가"
   (temp 0 심판이라 사실상 결정적으로 PASS).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-eval-judge-139.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/eval-139-judge.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-139-AI판정'
const CASE_NAME = '판정 케이스'
const QUESTION = 'A/B 테스트에서 중요한 것은?'
const AGENT = '옵시디언 매니저'
const CRITERION = '답변이 한국어로 작성되었는가'
const ASSERT_LABEL = `llm_judge: ${CRITERION}`
const DETAIL_LABEL = `llm_judge:${CRITERION}`

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

/** rows(활성 탭 내 DATASET_NAME 행들)의 innerText 중 pattern에 매치하는 게 하나라도 생길 때까지 폴링.
    real LLM 턴 + 심판 호출까지 겹쳐 137/138보다 오래 걸릴 수 있어 기본 180초 유지. */
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

  // ---------- 사전 정리(멱등화): 이전 실행 잔여 "e2e-139" 문제집이 있으면 먼저 삭제 ----------
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

  // ---------- 문제 추가: 기본 2기준 유지 + "채점 기준 추가"로 AI 판정(llm_judge) 기준 삽입 ----------
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.getByRole('button', { name: '문제 추가' }).click()
  await page.waitForTimeout(300)
  await page.getByPlaceholder('문제 이름 (예: RAG 필수 회귀)').fill(CASE_NAME)
  await page.getByPlaceholder('에이전트에게 보낼 질문').fill(QUESTION)

  await page.getByRole('button', { name: '채점 기준 추가' }).click()
  await page.waitForTimeout(200)
  // 새로 추가된 3번째 기준 행의 유형 Select — 기본값이 'trace_has'라 라벨이 "필수 도구/노드"로 뜨는
  // 그 행만 매칭(기존 2기준은 "오류 없음"/"답변 비어있지 않음"이라 겹치지 않음, 138과 동일 패턴).
  const newAssertSelect = page.locator('.ant-select').filter({ hasText: '필수 도구/노드' })
  await newAssertSelect.waitFor({ timeout: 5000 })
  await newAssertSelect.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: 'AI 판정' }).first().click()
  await page.waitForTimeout(200)
  const argInput = page.getByPlaceholder('예: 답변이 정중한 존댓말로 작성되었는가 — 심판 모델이 PASS/FAIL 판정')
  await argInput.waitFor({ timeout: 5000 })
  await argInput.fill(CRITERION)
  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)

  // ---------- E1: 케이스 카드 "3개 기준" + purple "llm_judge: ..." 태그 ----------
  // 이름+카운트 행(내부)과 assert 태그 행(형제)이 서로 다른 div라 hasText:'기준'만 쓰면 더 안쪽인
  // 이름+카운트 행(태그가 없는)이 .last()로 뽑힌다 — ASSERT_LABEL로 필터해 두 텍스트를 모두 담는
  // 가장 안쪽 컨테이너(=카드 전체)를 정확히 특정한다.
  const caseCard = page.locator('div').filter({ hasText: CASE_NAME }).filter({ hasText: ASSERT_LABEL }).last()
  const e1Text = await caseCard.innerText().catch(() => '')
  const e1HasCount = /3개 기준/.test(e1Text)
  const e1HasLabel = e1Text.includes(ASSERT_LABEL)
  const purpleTag = caseCard.locator('.ant-tag-purple', { hasText: 'llm_judge:' })
  const e1HasPurple = (await purpleTag.count()) > 0
  check(e1HasCount && e1HasLabel && e1HasPurple, `E1: "3개 기준"(${e1HasCount}) + purple "${ASSERT_LABEL}" 태그(라벨=${e1HasLabel}, purple클래스=${e1HasPurple}) [카드텍스트=${JSON.stringify(e1Text)}]`)

  // ---------- 에이전트 선택 → 시험 실행 ----------
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

  // ---------- E2: 실행 이력에 100% (1/1) (real LLM 턴+심판 호출 — 최대 180초 폴링) ----------
  const run = await pollFor(/ok/, '런(ok)')
  const runOk = run.texts.some((t) => /ok/.test(t) && /100% \(1\/1\)/.test(t))
  check(runOk, `E2: 실행 이력 ok+100% (1/1) (텍스트=${JSON.stringify(run.texts)})`)

  // ---------- 성적표 드로어 열기 ----------
  await runRows().first().click()
  await page.getByText(`성적표 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(500)

  // ---------- E3: 케이스 통과 + assert 상세에 llm_judge 행 초록 체크 ----------
  const resultCard = page.locator('div').filter({ hasText: CASE_NAME }).filter({ hasText: DETAIL_LABEL }).last()
  const e3Text = await resultCard.innerText().catch(() => '')
  const e3HasPassTag = (await resultCard.locator('.ant-tag-green', { hasText: '통과' }).count()) > 0
  const e3HasDetailLine = e3Text.includes(DETAIL_LABEL)
  const detailRow = resultCard.locator('div').filter({ hasText: DETAIL_LABEL }).last()
  const e3HasCheckIcon = (await detailRow.locator('svg[data-icon="check-circle"]').count()) > 0
  check(
    e3HasPassTag && e3HasDetailLine && e3HasCheckIcon,
    `E3: 케이스 "통과" green 태그(${e3HasPassTag}) + assert 상세 "${DETAIL_LABEL}" 행(${e3HasDetailLine}) + 초록 체크아이콘(${e3HasCheckIcon}) [카드텍스트=${JSON.stringify(e3Text)}]`
  )

  // ---------- "관측" Collapse 펼침 ----------
  await resultCard.getByText('관측 (답변·흔적)', { exact: true }).click()
  await page.waitForTimeout(500)

  // ---------- E4: "AI 판정" purple 태그 + "PASS" green 태그 + 기준 문장 + 판정 이유 문장 ----------
  const judgeBlock = resultCard.locator('div').filter({ hasText: 'AI 판정' }).filter({ hasText: CRITERION }).last()
  const judgeText = await judgeBlock.innerText().catch(() => '')
  const e4aPurple = (await judgeBlock.locator('.ant-tag-purple', { hasText: 'AI 판정' }).count()) > 0
  const e4bPass = (await judgeBlock.locator('.ant-tag-green', { hasText: 'PASS' }).count()) > 0
  const e4cCriterion = judgeText.includes(CRITERION)
  const critIdx = judgeText.indexOf(CRITERION)
  const reasonTail = critIdx >= 0 ? judgeText.slice(critIdx + CRITERION.length).trim() : ''
  const e4dReason = reasonTail.length > 0
  check(
    e4aPurple && e4bPass && e4cCriterion && e4dReason,
    `E4: "AI 판정" purple 태그(${e4aPurple}) + "PASS" green 태그(${e4bPass}) + 기준 문장(${e4cCriterion}) + 판정 이유 문장(${e4dReason}, 이유="${reasonTail}") [관측블록텍스트=${JSON.stringify(judgeText)}]`
  )

  // 사용자 UI/UX 확인용 스샷 — 관측 펼침 상태(AI 판정 이유 표시).
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)

  // ---------- 정리: 성적표 드로어 닫고 문제집 삭제 → E5 ----------
  await closeDrawer()
  await openDatasetTab()
  await page.waitForTimeout(300)
  await dsRow().first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
  const remaining = await dsRow().count()
  check(remaining === 0, `E5: 정리 — 목록에서 "${DATASET_NAME}" 사라짐(잔여 행=${remaining})`)

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
