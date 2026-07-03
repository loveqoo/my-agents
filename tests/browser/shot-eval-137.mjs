/* 스펙 137 e2e — 평가 하네스 제품화(새 "평가" 메뉴), 실 사용자 여정 그대로.
   문제집 생성 → 문제 추가(필수 rag: 채점 포함) → 옵시디언 매니저(조율형, 실 RAG)로 시험 실행 →
   폴링 대기 → 성적표(통과율·관측/trace_nodes) 확인 → 정리(삭제, CASCADE로 성적도 함께 사라짐).

   템플릿=shot-drawer-escape-135.mjs(로그인·provisionSuper·channel:'chrome' headless 패턴) +
   shot-admin-menu-065.mjs(관리자 그룹 메뉴 클릭은 getByText exact, 그룹 항목도 동일)
   + shot-broker-rag-inspector-130.mjs(옵시디언 매니저 실 RAG 질문 "A/B 테스트에서 중요한 것은?" —
   verify_137_eval_runner.py C2와 동일 질문, 응답에 "문해력"·"반응 패턴" 포함 확인됨).

   앱 코드 수정 없음 — 검증 전용. 실행 중 real LLM 호출이 있어 최대 180초 폴링한다.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-eval-137.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/eval-137.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-137-옵시디언 시험'
const CASE_NAME = 'rag 필수'
const QUESTION = 'A/B 테스트에서 중요한 것은?'
const AGENT = '옵시디언 매니저'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
const evalRunApiErrors = []
page.on('response', (r) => {
  if (/\/eval\/runs\/[0-9a-f-]+$/i.test(r.url()) && r.status() >= 400) {
    evalRunApiErrors.push(`${r.status()} ${r.url()}`)
  }
})

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

  // ---------- V1: 문제집 탭 + 새 문제집 버튼 ----------
  const tabVisible = await page.getByRole('tab', { name: '문제집' }).isVisible().catch(() => false)
  const newBtnVisible = await page.getByRole('button', { name: '새 문제집' }).isVisible().catch(() => false)
  check(tabVisible && newBtnVisible, `V1: "문제집" 탭(${tabVisible})·"새 문제집" 버튼(${newBtnVisible}) 표시`)

  // ---------- V2: 새 문제집 생성 → 목록에 행 등장 ----------
  await page.getByRole('button', { name: '새 문제집' }).click()
  await page.getByRole('dialog').getByText('새 문제집', { exact: true }).waitFor({ timeout: 5000 })
  await page.getByPlaceholder('이름 (예: 옵시디언 매니저 회귀 시험)').fill(DATASET_NAME)
  await page.getByRole('button', { name: '만들기' }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(500)
  // antd Tabs는 한 번 방문한 탭 패널을 언마운트하지 않고 aria-hidden으로만 감춘다 — 전역
  // `table tbody tr`는 숨은 패널(문제집/실행 이력)의 행까지 함께 잡혀 strict-mode 충돌·오탐이
  // 났다(probe로 확인: "문제집" 탭 방문 후엔 항상 2개 table이 DOM에 공존). getByRole('tabpanel')은
  // Playwright 접근성 트리 필터로 aria-hidden=true 패널을 자동 제외하므로 활성 탭 범위로 고정한다.
  const activePanel = () => page.getByRole('tabpanel')
  const dsRow = activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })
  const dsRowCount = await dsRow.count()
  check(dsRowCount === 1, `V2: 목록에 "${DATASET_NAME}" 행 등장 (count=${dsRowCount})`)

  // ---------- 행 클릭 → 드로어 → 문제 추가 ----------
  await dsRow.first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.getByRole('button', { name: '문제 추가' }).click()
  await page.waitForTimeout(300)

  await page.getByPlaceholder('문제 이름 (예: RAG 필수 회귀)').fill(CASE_NAME)
  await page.getByPlaceholder('에이전트에게 보낼 질문').fill(QUESTION)

  // 기본 2개 기준(오류 없음·답변 비어있지 않음) + "채점 기준 추가" → 새 행(기본 trace_has) 인자에 rag: 입력.
  await page.getByRole('button', { name: '채점 기준 추가' }).click()
  await page.waitForTimeout(200)
  const argInput = page.getByPlaceholder(/예: rag: \(RAG 필수\)/)
  await argInput.waitFor({ timeout: 5000 })
  await argInput.fill('rag:')

  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)

  // ---------- V3: 문제 카드 "3개 기준" + "trace_has: rag:" 태그 ----------
  const drawerText = await page.locator('#root').innerText().catch(() => '')
  const has3 = /3개 기준/.test(drawerText)
  const hasTraceTag = /trace_has:\s*rag:/.test(drawerText)
  check(has3 && hasTraceTag, `V3: "3개 기준"(${has3}) + "trace_has: rag:" 태그(${hasTraceTag})`)

  // ---------- 에이전트 선택 → 시험 실행 ----------
  await page.locator('.ant-select').filter({ hasText: '시험 칠 에이전트 선택' }).click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: AGENT }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '시험 실행' }).click()

  // ---------- V4: 성공 토스트 + "실행 이력" 탭 자동 전환 + "실행 중" 표시 ----------
  const toastOk = await page.getByText('시험 실행 시작', { exact: false }).first().waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
  const runsTabActive = await page.getByRole('tab', { name: '실행 이력', selected: true }).isVisible().catch(() => false)
  const runningVisible = await page.getByText('실행 중', { exact: true }).first().isVisible().catch(() => false)
  check(toastOk && runsTabActive && runningVisible, `V4: 토스트(${toastOk})·"실행 이력" 자동 전환(${runsTabActive})·"실행 중" 표시(${runningVisible})`)

  // 탭 전환은 EvalView의 `detail`(문제집 드로어) 상태를 안 건드린다 — 드로어가 열린 채 남아
  // 전체화면 마스크(zIndex 1000)가 아래 테이블 클릭을 가로챈다. 다음 행 클릭 전에 명시적으로 닫는다.
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // ---------- 폴링(최대 180초): 행이 ok + "100% (1/1)" 표시될 때까지 ----------
  const runRow = () => activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })
  let polled = false
  const deadline = Date.now() + 180000
  while (Date.now() < deadline) {
    const txt = await runRow().innerText().catch(() => '')
    if (/100% \(1\/1\)/.test(txt) && /ok/.test(txt)) {
      polled = true
      break
    }
    await page.waitForTimeout(5000)
    // 새로고침 버튼도 함께 눌러(자동 폴링과 이중 보강) 최신 상태를 확실히 반영.
    await page.getByRole('button', { name: '새로고침' }).click().catch(() => {})
    await page.waitForTimeout(300)
  }
  const finalRowText = await runRow().innerText().catch(() => '(행 없음)')
  check(polled, `V5: 행이 ok + "100% (1/1)" 표시 (최종 텍스트=${JSON.stringify(finalRowText)})`)

  // ---------- 행 클릭 → 성적표 드로어 ----------
  // V6/V7은 백엔드 GET /eval/runs/{id} 응답(성적표 상세 페이로드)에 의존한다 — 실패해도(예:
  // 500) 이 블록만 FAIL로 기록하고 스크립트는 계속 진행해(V8 정리까지 도달) 전체 결과를 낸다.
  await runRow().first().click()
  await page.waitForTimeout(1200)
  const scoreDrawerText = await page.locator('#root').innerText().catch(() => '')
  const v6a = /100%/.test(scoreDrawerText)
  const v6b = /1\/1 통과/.test(scoreDrawerText)
  const v6c = await page.getByText('통과', { exact: true }).first().isVisible().catch(() => false)
  const v6d = /trace_has:rag:/.test(scoreDrawerText)
  const apiErrNote = evalRunApiErrors.length ? ` [백엔드 오류: ${JSON.stringify([...new Set(evalRunApiErrors)])}]` : ''
  check(v6a && v6b && v6c && v6d, `V6: "100%"(${v6a})·"1/1 통과"(${v6b})·케이스 "통과" 태그(${v6c})·trace_has:rag: 체크(${v6d})${apiErrNote}`)

  // "관측" Collapse 펼치기(V6가 이미 깨졌으면 이 요소 자체가 없을 수 있음 — 존재할 때만 클릭).
  const obsToggle = page.getByText('관측 (답변·흔적)', { exact: true }).first()
  const obsToggleVisible = await obsToggle.isVisible().catch(() => false)
  if (obsToggleVisible) {
    await obsToggle.click().catch(() => {})
    await page.waitForTimeout(500)
  }
  const obsText = await page.locator('#root').innerText().catch(() => '')
  const v7a = /rag:Obsidian/.test(obsText)
  const v7hasOutput = /문해력|반응 패턴/.test(obsText)
  check(v7a && v7hasOutput, `V7: trace_nodes에 rag:Obsidian 포함(${v7a}) + 답변 텍스트 존재(${v7hasOutput})${apiErrNote}`)

  // ---------- 스크린샷 (성적표 상태 — 실패 시에도 당시 화면을 남긴다) ----------
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)

  // ---------- 정리: 드로어 닫고 "문제집" 탭 → 삭제 (V6/V7 결과와 무관하게 항상 시도) ----------
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  await page.getByRole('tab', { name: '문제집' }).click()
  await page.waitForTimeout(400)
  const delRow = activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })
  await delRow.first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
  const remaining = await activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME }).count()
  check(remaining === 0, `V8: 정리 — 목록에서 "${DATASET_NAME}" 사라짐(잔여 행=${remaining})`)

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
