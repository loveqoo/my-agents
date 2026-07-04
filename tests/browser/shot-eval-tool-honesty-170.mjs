/* 스펙 170 e2e — 평가 도구 정직성. 두 신호를 실 화면으로 검증:
   ② 출제 안내: agent 케이스에 도구 검사(trace_*)가 없으면 편집기에 안내 한 줄.
   ① 성적표 배지: 통과했지만 도구 흔적(rag/mcp/memory) 0이면 "도구 미사용" 배지 + 상단 집계.

   Plan-Execute Demo(RAG·MCP 없음)로 Mock LLM 실행 → 도구 미호출 통과 재현.
   템플릿=shot-eval-137.mjs(로그인·메뉴·문제집·실행·폴링·성적표·정리). 앱 수정 없음.
   실행: PLAYWRIGHT_DIR=<dir> ADMIN_EMAIL=.. ADMIN_PASSWORD=.. node tests/browser/shot-eval-tool-honesty-170.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/eval-tool-honesty-170.png'
const OUT_HINT = process.env.OUT_HINT ?? '/tmp/eval-tool-honesty-170-hint.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-170-도구정직성'
const CASE_NAME = '도구 검사 없는 케이스'
const QUESTION = '오늘 기분이 어때?'
const AGENT = 'plan-execute-demo' // select 옵션 라벨은 alias가 아니라 name

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
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })

  await page.getByText('평가', { exact: true }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '평가' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)

  // 멱등: 이전 실패로 남은 e2e-170 문제집을 먼저 정리(모달/행 충돌 방지)
  const panel0 = () => page.getByRole('tabpanel')
  for (let g = 0; g < 4; g++) {
    const leftover = panel0().locator('table tbody tr').filter({ hasText: DATASET_NAME })
    if (await leftover.count().catch(() => 0) === 0) break
    await leftover.first().getByRole('button').click().catch(() => {})
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: '삭제' }).click().catch(() => {})
    await page.waitForTimeout(600)
  }

  // 문제집 생성
  await page.getByRole('button', { name: '새 문제집' }).click()
  await page.getByRole('dialog').getByText('새 문제집', { exact: true }).waitFor({ timeout: 5000 })
  await page.getByPlaceholder('이름 (예: 옵시디언 매니저 회귀 시험)').fill(DATASET_NAME)
  await page.getByRole('button', { name: '만들기' }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  // 다이얼로그가 애니메이션 잔상으로 남아 클릭을 가로채는 것 방지 — 마스크가 사라질 때까지 대기
  await page.locator('.ant-modal-mask').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(500)
  const activePanel = () => page.getByRole('tabpanel')
  const dsRow = activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })
  await dsRow.first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })

  // 문제 추가 — 기본 기준만(trace_ 없음) → ② 안내가 떠야 함
  await page.getByRole('button', { name: '문제 추가' }).click()
  await page.waitForTimeout(300)
  await page.getByPlaceholder('문제 이름 (예: RAG 필수 회귀)').fill(CASE_NAME)
  await page.getByPlaceholder('에이전트에게 보낼 질문').fill(QUESTION)
  await page.waitForTimeout(200)

  // ② 검증: 안내 문구 표시
  const hintText = await page.locator('#root').innerText().catch(() => '')
  const hasHint = /도구 호출을 검사하는 기준이 없습니다/.test(hintText)
  check(hasHint, `②: 출제 안내("도구 호출을 검사하는 기준이 없습니다") 표시 (${hasHint})`)
  await page.screenshot({ path: OUT_HINT, fullPage: true }).catch(() => {})
  console.log('shot(hint):', OUT_HINT)

  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)

  // 에이전트 선택 → 실행
  await page.locator('.ant-select').filter({ hasText: '시험 칠 에이전트 선택' }).click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: AGENT }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '시험 실행' }).click()
  await page.getByText('시험 실행 시작', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // 폴링(최대 120초): 완료(ok + n/n)
  const runRow = () => activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })
  let polled = false
  const deadline = Date.now() + 120000
  while (Date.now() < deadline) {
    const txt = await runRow().innerText().catch(() => '')
    if (/\(1\/1\)/.test(txt) && /ok/.test(txt)) { polled = true; break }
    await page.waitForTimeout(4000)
    await page.getByRole('button', { name: '새로고침' }).click().catch(() => {})
    await page.waitForTimeout(300)
  }
  check(polled, `실행 완료 폴링 (${polled})`)

  // 성적표 열기
  await runRow().first().click()
  await page.waitForTimeout(1200)
  const scoreText = await page.locator('#root').innerText().catch(() => '')
  const passed = /1\/1 통과/.test(scoreText)
  const badge = /도구 미사용/.test(scoreText)
  check(passed, `케이스 통과(1/1) (${passed})`)
  check(badge, `①: "도구 미사용" 배지/집계 표시 (${badge})`)

  // 관측 펼쳐 trace_nodes 실값 확인(정직 보고)
  const obsToggle = page.getByText('관측 (답변·흔적)', { exact: true }).first()
  if (await obsToggle.isVisible().catch(() => false)) { await obsToggle.click().catch(() => {}); await page.waitForTimeout(500) }
  const obsText = await page.locator('#root').innerText().catch(() => '')
  const hasToolTrace = /rag:|mcp:|memory:/.test(obsText)
  console.log(`  trace에 도구 흔적(rag/mcp/memory) 존재? ${hasToolTrace} — 배지는 도구 흔적 0일 때만 떠야 함`)
  check(!hasToolTrace === badge, `일관성: 도구 흔적 없음(${!hasToolTrace}) ⇔ 배지 표시(${badge})`)

  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot(scorecard):', OUT)

  // 정리
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  await page.getByRole('tab', { name: '문제집' }).click()
  await page.waitForTimeout(400)
  const delRow = activePanel().locator('table tbody tr').filter({ hasText: DATASET_NAME })
  await delRow.first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
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
