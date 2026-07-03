/* 스펙 141 e2e — 평가 5탄: 모델별 비교 실행 + 격자 뷰.
   문제집 생성(agent 종류, 잔여 사전 삭제) → 문제 추가("rag 사용 문제" + 3번째 기준
   output_contains:"문해력" — qwen3.6-35b는 실 RAG 근거를 반영한 실 답변에 이 단어가 포함되어 통과,
   mock-llm은 컨텍스트를 무시한 고정 템플릿 응답(mock_remote.py `_mock_reply` — 마지막 user 메시지만
   에코, 위임 결과 무시)이라 이 단어가 없어 실패, 같은 문제·같은 질문에서 모델만 갈라 **결정적으로
   분기**) → 드로어에서 옵시디언 매니저 + 모델 다중 Select에서 qwen3.6-35b·mock-llm 2개 선택 → 버튼
   라벨 "2개 모델 비교 실행"(X1) → 실행 → 토스트 "모델 격자" 언급(X2) → "모델 격자" 탭에서 그룹
   Select(모델 2개)(X3) → 두 열 완료까지 폴링(최대 240초 — EvalView가 5초 간격으로 running 런을 자동
   재조회하고 MatrixView가 그 상태 변화를 구독해 갱신하므로 탭 전환 없이도 반영됨, 순차 실행 큐 여유로
   상한만 넉넉히) → 격자 행 확인, 두 모델 결과가 갈리면 통과(X4) → "다른 결과만" 스위치 on/off(X5) →
   셀 클릭 → 성적표 드로어(X6) → 스샷 → 문제집 삭제(CASCADE로 관련 런도 제거)(X7).

   이상 징후(스펙 지시와 다르게 구현 — 회귀 아님, 실측으로 발견·수정): 애초 지시는 3번째 기준을
   trace_has:"rag:"로 써서 "qwen은 RAG를 써서 통과·mock-llm은 안 써서 실패"를 기대했으나, 실측
   결과 **두 모델 다 통과**했다(1차 실행 로그: 두 열 모두 "통과"·100%). 원인을 packages/agent/src/
   agent/flows/orchestrate.py에서 확인: 조율형 에이전트의 위임 대상 선정(`select`→`rank_candidates`)은
   질의-후보 **어휘 토큰 겹침만으로 결정되는 순수 결정적 로직**이라 모델 선택과 무관하게 항상
   rag:Obsidian을 위임한다 — LLM은 마지막 `synthesize` 단계에서 그 위임 결과를 문장으로 종합할 때만
   쓰인다. 즉 trace_has:"rag:"는 이 에이전트 구조상 모델별로 갈릴 수 없는 신호였다(구조적으로 항상
   양쪽 다 rag: 노드를 탄다 — 플레이키 아니라 영구 불변). 그래서 실제로 모델에 따라 달라지는 유일한
   지점(synthesize의 LLM 출력 문장)을 겨눈 output_contains:"문해력"으로 교체했다 — 이 마커는
   verify_137_eval_runner.py C2c가 이미 같은 질문·같은 에이전트에서 "문해력" 또는 "반응 패턴" 포함을
   실측 검증해 둔 값이고, probe(2회 반복 직접 실행, /tmp/probe141.py)로 완전히 동일한 문장이 재현되는
   것도 확인했다(결정적 — 온도/샘플링 변동 없음). mock-llm은 위임 결과를 전혀 반영하지 않는 고정
   템플릿이라 이 단어가 원천적으로 나올 수 없다 — genuinely deterministic한 분기.

   템플릿=shot-eval-judge-139.mjs(로그인·평가 메뉴·문제집/케이스 생성·실행·폴링·멱등 사전정리 재사용,
   antd 6 셀렉터 주의사항 동일 적용 — .ant-select 사용·getByRole('tabpanel')로 활성 탭 스코프 고정·
   드로어는 Escape로 닫아 마스크가 아래 클릭을 가로채지 않게 함·"div 필터 후 .last()"로 최내부
   컨테이너 특정) + shot-eval-137.mjs("옵시디언 매니저" 실 RAG 질문 패턴).

   실 모델 사전조건(레지스트리 seed): "qwen3.6-35b"·"mock-llm" 둘 다 chat 모델로 등록되어 있어야
   하고, "옵시디언 매니저" 에이전트 기본 모델이 qwen3.6-35b여야 한다(현재 dev DB에서 확인됨). 앱 코드
   수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-eval-matrix-141.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/eval-141-matrix.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-141-격자'
const CASE_NAME = 'rag 사용 문제'
const QUESTION = 'A/B 테스트에서 중요한 것은?'
const AGENT = '옵시디언 매니저'
const MODEL_A = 'qwen3.6-35b'
const MODEL_B = 'mock-llm'

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

async function closeDrawer() {
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}

async function openDatasetTab() {
  await page.getByRole('tab', { name: '문제집' }).click()
  await page.waitForTimeout(400)
}

async function openMatrixTab() {
  await page.getByRole('tab', { name: '모델 격자' }).click()
  await page.waitForTimeout(400)
}

/** 격자 표(활성 탭 내 table)가 두 모델 헤더를 모두 보이고, "실행 중" 텍스트가 사라질 때까지 폴링.
    EvalView 최상위 useEffect가 running 런이 남아있는 한 5초 간격으로 loadRuns()를 돌리고,
    MatrixView는 group.runs 상태 변화를 구독해 재조회하므로 이 탭에 머물러 있는 것만으로 갱신된다
    (탭 전환/새로고침 버튼 없이도 반영 — 코드 확인: EvalMatrix.tsx useEffect deps에 runs 상태 join). */
async function pollGridDone(deadlineMs = 240000) {
  const deadline = Date.now() + deadlineMs
  let tableText = ''
  while (Date.now() < deadline) {
    const tbl = activePanel().locator('table')
    if ((await tbl.count()) > 0) {
      tableText = await tbl.innerText().catch(() => '')
      const hasBothCols = tableText.includes(MODEL_A) && tableText.includes(MODEL_B)
      if (hasBothCols && !/실행 중/.test(tableText)) return { ok: true, text: tableText }
    }
    await page.waitForTimeout(5000)
  }
  return { ok: false, text: tableText }
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

  // ---------- 사전 정리(멱등화): 이전 실행 잔여 "e2e-141" 문제집이 있으면 먼저 삭제 ----------
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

  // ---------- 문제 추가: 기본 2기준 + "채점 기준 추가"로 output_contains 기준에 "문해력" 입력 ----------
  // 헤더 코멘트의 "이상 징후" 참조 — trace_has:"rag:"는 이 에이전트 구조상 모델별로 갈리지 않아
  // output_contains:"문해력"(synthesize 단계의 실 LLM 출력에서만 나오는 마커)로 교체했다. 신규 assert
  // 행 기본 유형이 trace_has(라벨 "필수 도구/노드")라 드롭다운에서 "답변에 포함"으로 바꿔야 한다.
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.getByRole('button', { name: '문제 추가' }).click()
  await page.waitForTimeout(300)
  await page.getByPlaceholder('문제 이름 (예: RAG 필수 회귀)').fill(CASE_NAME)
  await page.getByPlaceholder('에이전트에게 보낼 질문').fill(QUESTION)

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
  await argInput.fill('문해력')
  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)

  const CARD_LABEL = 'output_contains: 문해력' // 케이스 카드 태그 텍스트(Tag 렌더 `${type}: ${arg}`)
  const DETAIL_LABEL = 'output_contains:문해력' // 성적표 assert 상세 이름(공백 없음 — build_asserts f-string)
  const caseCard = page.locator('div').filter({ hasText: CASE_NAME }).filter({ hasText: CARD_LABEL }).last()
  const caseText = await caseCard.innerText().catch(() => '')
  console.log(`(setup) 케이스 카드 "3개 기준"(${/3개 기준/.test(caseText)}) + "${CARD_LABEL}" 태그(${caseText.includes(CARD_LABEL)})`)

  // ---------- 에이전트 선택 + 모델 다중 선택(qwen3.6-35b, mock-llm) ----------
  await page.locator('.ant-select').filter({ hasText: '시험 칠 에이전트 선택' }).click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: AGENT }).first().click()
  await page.waitForTimeout(300)

  const modelSelect = page.locator('.ant-select').filter({ hasText: '모델 비교' })
  await modelSelect.click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: MODEL_A }).first().click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: MODEL_B }).first().click()
  await page.waitForTimeout(200)
  // 드롭다운만 닫는다(Escape는 열려있는 최상위 오버레이부터 닫으므로 드로어는 유지됨).
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // ---------- X1: 버튼 라벨 "2개 모델 비교 실행" ----------
  // getByRole 접근성 이름에는 아이콘(<Icon name="thunderbolt"/> → antd 아이콘의 aria-label="thunderbolt")도
  // 섞여 들어간다 — exact:true는 실패하므로(137/139/140의 "시험 실행" 버튼도 동일 이유로 exact 없이 매칭)
  // 부분 매칭(기본값)으로 라벨 문구 포함 여부만 확인한다.
  const startBtn = page.getByRole('button', { name: '2개 모델 비교 실행' })
  const x1 = await startBtn.isVisible().catch(() => false)
  check(x1, `X1: 버튼 라벨 "2개 모델 비교 실행" 표시(${x1})`)

  // ---------- 실행 → X2: 토스트에 "모델 격자" 언급 ----------
  await startBtn.click()
  await page.locator('.ant-message-notice').first().waitFor({ timeout: 8000 }).catch(() => {})
  const toastText = (await page.locator('.ant-message-notice').first().textContent().catch(() => '')) ?? ''
  const x2 = toastText.includes('모델 격자')
  check(x2, `X2: 토스트에 "모델 격자" 언급(${x2}) [토스트텍스트=${JSON.stringify(toastText)}]`)

  await closeDrawer()

  // ---------- "모델 격자" 탭 이동 → X3: 그룹 Select에 방금 그룹(모델 2개) 표시 ----------
  await openMatrixTab()
  const groupSelect = activePanel().locator('.ant-select').first()
  await groupSelect.click()
  await page.waitForTimeout(300)
  const groupOption = page.locator('.ant-select-item-option').filter({ hasText: DATASET_NAME }).filter({ hasText: '모델 2개' }).first()
  const x3 = (await groupOption.count()) > 0
  await groupOption.click().catch(() => {})
  await page.waitForTimeout(400)
  check(x3, `X3: 그룹 Select에 "${DATASET_NAME}" · "모델 2개" 옵션 표시(${x3})`)

  // ---------- 두 열 완료까지 폴링(최대 240초 — 순차 실행이라 여유) ----------
  const grid = await pollGridDone(240000)
  console.log(`(폴링) 격자 완료(${grid.ok}) [표텍스트=${JSON.stringify(grid.text)}]`)

  // ---------- X4: 행 "rag 사용 문제" — qwen 통과(green) + mock-llm과 결과가 갈림 ----------
  const headers = await activePanel().locator('table thead th').allInnerTexts().catch(() => [])
  const aIdx = headers.indexOf(MODEL_A)
  const bIdx = headers.indexOf(MODEL_B)
  const ragRow = activePanel().locator('table tbody tr').filter({ hasText: CASE_NAME })
  const ragCells = await ragRow.locator('td').allInnerTexts().catch(() => [])
  const totalRow = activePanel().locator('table tbody tr', { hasText: '합계' })
  const totalCells = await totalRow.locator('td').allInnerTexts().catch(() => [])
  const aCellTd = ragRow.locator('td').nth(aIdx)
  const aPass = (await aCellTd.locator('.ant-tag-green', { hasText: '통과' }).count().catch(() => 0)) > 0
  const rowDiffers = aIdx >= 0 && bIdx >= 0 && (ragCells[aIdx] ?? '').trim() !== (ragCells[bIdx] ?? '').trim()
  const totalDiffers = aIdx >= 0 && bIdx >= 0 && (totalCells[aIdx] ?? '').trim() !== (totalCells[bIdx] ?? '').trim()
  const x4 = aPass && (rowDiffers || totalDiffers)
  check(
    x4,
    `X4: "${CASE_NAME}" 행 — ${MODEL_A} 통과(green)(${aPass}) + 두 모델 결과가 갈림(행=${rowDiffers}, 합계=${totalDiffers}) ` +
      `[행셀=${JSON.stringify(ragCells)}, 합계셀=${JSON.stringify(totalCells)}, 헤더=${JSON.stringify(headers)}]`
  )

  // ---------- X5: "다른 결과만" 스위치 on/off 동작 확인 — 결과가 갈리므로 켜도 행이 계속 보여야 함 ----------
  const diffSwitch = activePanel().locator('.ant-switch')
  const isChecked = async () => ((await diffSwitch.getAttribute('class').catch(() => '')) ?? '').includes('ant-switch-checked')
  await diffSwitch.click()
  await page.waitForTimeout(300)
  const onState1 = await isChecked()
  const rowVisibleOn1 = (await activePanel().locator('table tbody tr').filter({ hasText: CASE_NAME }).count()) > 0
  await diffSwitch.click()
  await page.waitForTimeout(300)
  const offState = await isChecked()
  const rowVisibleOff = (await activePanel().locator('table tbody tr').filter({ hasText: CASE_NAME }).count()) > 0
  await diffSwitch.click()
  await page.waitForTimeout(300)
  const onState2 = await isChecked()
  const rowVisibleOn2 = (await activePanel().locator('table tbody tr').filter({ hasText: CASE_NAME }).count()) > 0
  const x5 = onState1 && rowVisibleOn1 && !offState && rowVisibleOff && onState2 && rowVisibleOn2
  check(
    x5,
    `X5: "다른 결과만" on(체크=${onState1},행표시=${rowVisibleOn1}) → off(체크=${offState},행표시=${rowVisibleOff}) → on(체크=${onState2},행표시=${rowVisibleOn2})`
  )

  // ---------- X6: 셀 클릭 → 성적표 드로어(해당 모델 런) ----------
  // qwen 열 셀을 클릭 — 드로어 안 assert 상세에 DETAIL_LABEL 행 + 초록 체크(그 런이 실제로 qwen임을
  // 결정적으로 증명, mock-llm 런이었다면 이 assert는 실패로 나온다). 이 앱의 Drawer는 antd Drawer가
  // 아니라 커스텀 컴포넌트(admin/shared.tsx) — ".ant-drawer-body" 클래스가 없어 137/139/140과 동일하게
  // "div 필터 후 .last()"로 최내부 결과 카드를 특정한다.
  await ragRow.locator('td').nth(aIdx).click()
  const drawerOpened = await page.getByText(`성적표 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
  await page.waitForTimeout(500)
  const resultCard = page.locator('div').filter({ hasText: CASE_NAME }).filter({ hasText: DETAIL_LABEL }).last()
  const x6Text = await resultCard.innerText().catch(() => '')
  const x6HasCase = x6Text.includes(CASE_NAME)
  const x6HasPassTag = (await resultCard.locator('.ant-tag-green', { hasText: '통과' }).count().catch(() => 0)) > 0
  const detailRow = resultCard.locator('div').filter({ hasText: DETAIL_LABEL }).last()
  const x6HasCheckIcon = (await detailRow.locator('svg[data-icon="check-circle"]').count().catch(() => 0)) > 0
  const x6 = drawerOpened && x6HasCase && x6HasPassTag && x6HasCheckIcon
  check(
    x6,
    `X6: 셀 클릭 → 성적표 드로어 열림(${drawerOpened}) + 케이스명(${x6HasCase}) + "통과" green 태그(${x6HasPassTag}) + ` +
      `"${DETAIL_LABEL}" 초록 체크(${x6HasCheckIcon}) [카드텍스트=${JSON.stringify(x6Text)}]`
  )

  // 사용자 UI/UX 확인용 스샷 — 성적표 드로어가 겹친 상태라 우선 닫고 격자+합계 행이 잘 보이는 상태로.
  await closeDrawer()
  await page.waitForTimeout(400)
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)

  // ---------- 정리: "문제집" 탭 → 삭제 → X7 ----------
  await openDatasetTab()
  await page.waitForTimeout(300)
  await dsRow().first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
  const remaining = await dsRow().count()
  check(remaining === 0, `X7: 정리 — 목록에서 "${DATASET_NAME}" 사라짐(잔여 행=${remaining})`)

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
