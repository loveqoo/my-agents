/* 스펙 142 e2e — 평가 6탄: 골든셋 자동 생성(컬렉션 → RAG 문제집).
   문제집 탭 "컬렉션에서 생성" 버튼 → 모달(안내 문구+컬렉션 Select+이름 자동 제안+문제 수, H1) →
   컬렉션 "Obsidian" 선택 시 이름이 "Obsidian 골든셋"으로 자동 제안되는지 확인(H2) → 이름을
   "e2e-142-골든셋"으로 교체, 문제 수 5 → 생성 → 성공 토스트 → 목록에 "생성 중…" 행 등장 →
   백그라운드 생성(LLM 호출 N회라 지연) 완료까지 최대 180초 폴링(설명이 "자동 생성 N건"으로
   바뀔 때까지, 5초 간격으로 "문제집 탭 재클릭 또는 페이지 이동 왕복"로 목록 새로고침 — H3) →
   드로어에서 생성된 문제 카드 N개 확인(이름 "골든 i · 파일명" + 질문이 "?"로 끝남 + "3개 기준"
   태그 + rag_source_contains 기준 포함, H4) → 컬렉션 "Obsidian"으로 시험 실행(자기일관 골든이라
   생성 질문이 다른 청크로 검색될 수 있어 100%가 아닐 수 있음 — 점수 ≥60%면 통과, H5) → 성적표에서
   케이스별 rag_source_contains 채점(체크 아이콘) 확인(H6) → 스크린샷(생성 문제 카드가 보이는
   드로어, 사용자 확인용) → 문제집 삭제 정리(H7).

   템플릿=shot-eval-rag-140.mjs(로그인·평가 메뉴·RAG 실행·폴링·멱등 정리 재사용, antd 6 셀렉터
   주의사항 동일 적용 — .ant-select 사용·getByRole('tabpanel')로 활성 탭 스코프 고정·드로어는
   Escape로 닫아 마스크가 아래 클릭을 가로채지 않게 함).

   앱 코드 수정 없음 — 검증 전용. 백엔드는 실 기본 chat 모델로 청크당 질문 1개를 생성하므로(스펙
   142 설계), 로컬 LLM 호출 5회 만큼 시간이 걸린다 — 인내심 있게 폴링(최대 180초).

   이상 징후(앱 렌더링 특이점, 회귀 아님 — 발견만 기록): 이 프로젝트의 Drawer는 antd Drawer가
   아니라 자체 구현(shared/Drawer, position:fixed 오버레이 순수 div) — ant-drawer-* 클래스가 전혀
   없다(className 전부 빈 문자열, DOM 확인 완료). 카드는 인라인 style(`border: 1px solid
   var(--color-border-secondary)`) 문자열로 구조적으로 특정한다.

   이상 징후 2(실 환경 재현성 문제, 스크립트 결함 아님): 현재 Obsidian 컬렉션은 문서 1개·청크 7개뿐이고,
   기본 chat 모델(로컬 mlx qwen3.6-35b)이 eval_golden.py의 "질문 1개, 첫 줄에 물음표로 끝남" 형식
   지시를 절반 이상 어긴다(한국어 격식체 종결 "-는가/-인가"를 물음표 없이 냄 — `_parse_question`이
   설계대로 fail-closed 거부). 동일 청크 7개에 대해 반복 호출해도 결과가 거의 결정적이라(같은 청크가
   매번 같은 성패), count=5 요청 시 실측 N=1~2건에 수렴 — 스펙이 가정한 "N≥3"에 못 미치는 경우가
   흔하다(직접 진단: /packages/api/src/api/eval_golden.py 호출을 격리 실행해 원시 LLM 응답 확인,
   재현 다회). 셀렉터·플로우는 정상 동작 확인(H1/H2/H5/H6/H7 반복 통과, H4는 N만큼 정확히 채움) —
   막힌 지점은 생성기 프롬프트의 형식 준수율이지 이 테스트가 아니다. count·컬렉션은 그대로(스펙
   지시 준수), 재현 조건을 코멘트로 남긴다.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-eval-golden-142.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/eval-142-golden.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-142-골든셋'
const COLLECTION = 'Obsidian'
const REQUEST_COUNT = 5

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

async function gotoEval() {
  await page.getByRole('menuitem', { name: '평가' }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '평가' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

/** 실행 이력 탭: runRows(활성 탭 내 DATASET_NAME 행들)의 innerText 중 predicate가 참일 때까지
    "새로고침" 버튼으로 폴링(140 템플릿과 동일). */
async function pollRuns(predicate, label, deadlineMs = 120000) {
  const deadline = Date.now() + deadlineMs
  let lastTexts = []
  while (Date.now() < deadline) {
    lastTexts = await runRows().allInnerTexts().catch(() => [])
    if (lastTexts.some(predicate)) return { ok: true, texts: lastTexts }
    await page.waitForTimeout(2000)
    await page.getByRole('button', { name: '새로고침' }).click().catch(() => {})
    await page.waitForTimeout(300)
  }
  return { ok: false, texts: lastTexts }
}

/** 문제집 탭: dsRow의 description이 predicate를 만족할 때까지 폴링. 백그라운드 생성 완료는
    EvalView 마운트 시 1회만 도는 loadDatasets()로만 반영되므로(러너처럼 실행 중 폴링 useEffect가
    없음), "문제집 탭 재클릭"이 아니라 **다른 메뉴로 이동 후 평가로 복귀**(컴포넌트 리마운트 →
    loadDatasets 재호출)로 새로고침한다 — 지시된 "페이지 이동 왕복" 경로. */
async function pollDatasetDesc(predicate, deadlineMs = 180000) {
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

  // ---------- 사전 정리(멱등화): 이전 실행 잔여 "e2e-142-골든셋" 문제집이 있으면 먼저 삭제 ----------
  let preExisting = await dsRow().count()
  while (preExisting > 0) {
    await dsRow().first().getByRole('button').click()
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: '삭제' }).click()
    await page.waitForTimeout(600)
    preExisting = await dsRow().count()
  }
  console.log(`(사전정리) 잔여 "${DATASET_NAME}" 문제집 제거 완료(count=${preExisting})`)

  // ---------- H1: "컬렉션에서 생성" 버튼 → 모달 열림(안내 문구+컬렉션 Select+이름+문제 수) ----------
  await page.getByRole('button', { name: '컬렉션에서 생성' }).click()
  await page.getByRole('dialog').getByText('컬렉션에서 문제집 생성', { exact: true }).waitFor({ timeout: 5000 })
  const modal = page.getByRole('dialog')
  const modalText = await modal.innerText().catch(() => '')
  const h1HasIntro = /자동 출제/.test(modalText)
  const collectionSelectModal = modal.locator('.ant-select').filter({ hasText: '컬렉션 선택' })
  const nameInput = page.getByPlaceholder('문제집 이름')
  const countSelectModal = modal.locator('.ant-select').last()
  const h1HasCollectionSelect = (await collectionSelectModal.count()) > 0
  const h1HasNameInput = (await nameInput.count()) > 0
  const h1HasCountSelect = (await countSelectModal.count()) > 0 && /문제 수/.test(modalText)
  check(
    h1HasIntro && h1HasCollectionSelect && h1HasNameInput && h1HasCountSelect,
    `H1: 모달 열림 — 안내 문구(${h1HasIntro}) + 컬렉션 Select(${h1HasCollectionSelect}) + 이름(${h1HasNameInput}) + 문제 수(${h1HasCountSelect})`
  )

  // ---------- 컬렉션 "Obsidian" 선택 → H2: 이름 자동 제안 "Obsidian 골든셋" ----------
  await collectionSelectModal.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: COLLECTION }).first().click()
  await page.waitForTimeout(300)
  const suggestedName = await nameInput.inputValue()
  check(suggestedName === `${COLLECTION} 골든셋`, `H2: 이름 자동 제안="${COLLECTION} 골든셋"(실제="${suggestedName}")`)

  // ---------- 이름을 e2e 이름으로 교체 + 문제 수 5 ----------
  await nameInput.fill('')
  await nameInput.fill(DATASET_NAME)
  await countSelectModal.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option').filter({ hasText: /^5$/ }).first().click()
  await page.waitForTimeout(200)

  // ---------- 생성 → 성공 토스트 ----------
  await page.getByRole('dialog').getByRole('button', { name: '생성' }).click()
  await page.getByText('생성 시작', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  await page.getByRole('dialog').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(500)

  // ---------- 목록에 행 등장, 설명에 "생성 중…" ----------
  const listedAfterCreate = (await dsRow().count()) === 1
  check(listedAfterCreate, `목록에 "${DATASET_NAME}" 행 등장(count=${await dsRow().count()})`)

  // ---------- H3: 백그라운드 생성 완료 폴링(최대 180초) — 설명이 "자동 생성 N건(N≥3)"으로 ----------
  const genRe = /자동 생성 (\d+)건/
  const gen = await pollDatasetDesc((t) => genRe.test(t))
  const genMatch = gen.texts.find((t) => genRe.test(t))
  const madeCount = genMatch ? parseInt(genRe.exec(genMatch)[1], 10) : 0
  check(gen.ok && madeCount >= 3, `H3: 설명 "자동 생성 N건(N≥3)" — N=${madeCount} (텍스트=${JSON.stringify(gen.texts)})`)

  // ---------- 행 클릭 → 드로어 ----------
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(400)

  // ---------- H4: 문제 카드 N개 — 이름 "골든 i · 파일명" + 질문 "?" + "3개 기준" + rag_source_contains ----------
  // 이 프로젝트의 Drawer는 antd Drawer가 아니라 자체 구현(shared/Drawer) — ant-drawer-* 클래스가
  // 없다(DOM 확인: 순수 div 오버레이, className 전부 빈 문자열). 카드는 인라인 style로 특정한다.
  const cardLoc = page.locator('div[style*="border: 1px solid var(--color-border-secondary)"]').filter({ hasText: '개 기준' })
  const cardCount = await cardLoc.count()
  const cardTexts = await cardLoc.allInnerTexts().catch(() => [])
  const h4CountOk = cardCount === madeCount && cardCount >= 3
  const h4NameOk = cardTexts.every((t) => /골든\s*\d+\s*·/.test(t))
  const h4QuestionOk = cardTexts.every((t) => {
    // 카드 텍스트: 이름줄 \n "N개 기준" \n 질문줄 \n 태그들 — 질문은 물음표로 끝나는 줄이 존재해야 함.
    const lines = t.split('\n').map((l) => l.trim()).filter(Boolean)
    return lines.some((l) => l.endsWith('?'))
  })
  const h4AssertCountOk = cardTexts.every((t) => t.includes('3개 기준'))
  const h4SourceTagOk = cardTexts.every((t) => t.includes('rag_source_contains'))
  check(
    h4CountOk && h4NameOk && h4QuestionOk && h4AssertCountOk && h4SourceTagOk,
    `H4: 문제 카드 개수=${cardCount}(기대 ${madeCount}, ${h4CountOk}) + 이름패턴(${h4NameOk}) + 질문 물음표(${h4QuestionOk}) + "3개 기준"(${h4AssertCountOk}) + rag_source_contains 태그(${h4SourceTagOk})`
  )
  if (!h4CountOk || !h4NameOk || !h4QuestionOk || !h4AssertCountOk || !h4SourceTagOk) {
    console.log('카드 텍스트=', JSON.stringify(cardTexts))
  }

  // 사용자 UI/UX 확인용 스샷 — 생성된 문제 카드들이 보이는 드로어 상태.
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)

  // ---------- 컬렉션 "Obsidian" 선택 → 시험 실행 ----------
  const runCollectionSelect = page.locator('.ant-select').filter({ hasText: '시험 칠 RAG 컬렉션 선택' })
  await runCollectionSelect.first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: COLLECTION }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '시험 실행' }).click()
  await page.getByText('시험 실행 시작', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  await page.getByRole('tab', { name: '실행 이력', selected: true }).waitFor({ timeout: 8000 }).catch(() => {})
  await closeDrawer()

  // ---------- H5: 실행 이력에 ok + 점수 ≥60% (자기일관 — 생성 질문 일부가 다른 청크로 검색될 수 있음) ----------
  const run = await pollRuns((t) => /\bok\b/.test(t) && /\d+% \(\d+\/\d+\)/.test(t))
  const scoreLine = run.texts.find((t) => /\bok\b/.test(t))
  const scoreMatch = scoreLine ? /(\d+)% \((\d+)\/(\d+)\)/.exec(scoreLine) : null
  const scorePct = scoreMatch ? parseInt(scoreMatch[1], 10) : -1
  const h5 = run.ok && scorePct >= 60
  check(h5, `H5: 실행 이력 ok + 점수≥60%(실제=${scorePct}%) [텍스트=${JSON.stringify(run.texts)}]`)

  // ---------- 성적표 드로어 열기 ----------
  await runRows().first().click()
  await page.getByText(`성적표 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(500)

  // ---------- H6: 케이스별 rag_source_contains 채점 표시 ----------
  const resultCards = page.locator('div[style*="border: 1px solid var(--color-border-secondary)"]').filter({ hasText: '통과' }).or(
    page.locator('div[style*="border: 1px solid var(--color-border-secondary)"]').filter({ hasText: '실패' })
  )
  const resultCount = await resultCards.count()
  const resultTexts = await resultCards.allInnerTexts().catch(() => [])
  const h6CountOk = resultCount === madeCount
  const h6DetailOk = resultTexts.every((t) => /rag_source_contains:/.test(t))
  // 아이콘 확인 — 각 카드 안에 check-circle 또는 close-circle svg가 최소 1개는 있어야(assert 채점 렌더).
  const iconCounts = []
  for (let i = 0; i < resultCount; i++) {
    const card = resultCards.nth(i)
    const n = (await card.locator('svg[data-icon="check-circle"], svg[data-icon="close-circle"]').count())
    iconCounts.push(n)
  }
  const h6IconOk = iconCounts.every((n) => n > 0)
  check(
    h6CountOk && h6DetailOk && h6IconOk,
    `H6: 케이스 결과 카드=${resultCount}(기대 ${madeCount}, ${h6CountOk}) + rag_source_contains 상세 행(${h6DetailOk}) + 채점 아이콘(${h6IconOk}) [아이콘개수=${JSON.stringify(iconCounts)}]`
  )
  if (!h6CountOk || !h6DetailOk || !h6IconOk) {
    console.log('결과 카드 텍스트=', JSON.stringify(resultTexts))
  }

  // ---------- 정리: 성적표 드로어 닫고 문제집 삭제 → H7 ----------
  await closeDrawer()
  await openDatasetTab()
  await page.waitForTimeout(300)
  await dsRow().first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
  const remaining = await dsRow().count()
  check(remaining === 0, `H7: 정리 — 목록에서 "${DATASET_NAME}" 사라짐(잔여 행=${remaining})`)

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
