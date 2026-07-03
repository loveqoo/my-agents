/* 스펙 140 e2e — 평가 4탄: RAG 컬렉션 시험(kind='rag') 축.
   "새 문제집" 모달에서 종류를 "RAG 컬렉션 시험"으로 바꿔 생성(G1: 목록 종류 태그="rag") →
   문제 추가(기본 2기준 + "채점 기준 추가"로 rag_hits_gte 기준 삽입, G2: "3개 기준"+"rag_hits_gte: 1"
   태그) → 드로어 상단 Select placeholder가 "시험 칠 RAG 컬렉션 선택"인지 확인(G3) → 실 컬렉션
   "Obsidian" 선택 → 시험 실행(검색만이라 real LLM 턴 없음 — 폴링 짧게 120초) → 실행 이력 100%(1/1)+
   "RAG · Obsidian" 대상(G4) → 성적표: 케이스 통과 + "rag_hits_gte:1" 체크(G5) → "관측" 펼침에서
   유사도 태그(0.xxx)+근거 파일명 행 + 검색 결과 본문 텍스트(G6) → 스크린샷 → 문제집 삭제 정리(G7).

   템플릿=shot-eval-judge-139.mjs(로그인·평가 메뉴·문제집/케이스 생성·실행·폴링·멱등 사전정리 재사용,
   antd 6 셀렉터 주의사항 동일 적용 — .ant-select 사용·getByRole('tabpanel')로 활성 탭 스코프 고정·
   드로어는 Escape로 닫아 마스크가 아래 클릭을 가로채지 않게 함·"div 필터 후 .last()"로 최내부
   컨테이너 특정).

   앱 코드 수정 없음 — 검증 전용. 실 Obsidian 컬렉션(읽기 전용 검색)을 사용하므로 세션/메모리 오염 없음.

   이상 징후(앱 렌더링 특이점, 회귀 아님 — 발견만 기록): RAG 문제집 드로어에서 "채점 기준 추가"로
   새로 마운트된 3번째 assert Select가 초기값 라벨("필수 도구/노드") 대신 원시값("trace_has")을
   그대로 표시함(agent 문제집 드로어의 동일 흐름은 정상 — kind='rag' 드로어에서만 재현, 옵션을 한 번
   바꿔 선택하면 이후엔 라벨이 정상 표시됨). 라벨 텍스트 매칭 대신 폼 컨테이너 내 "마지막 Select"로
   구조적으로 특정해 우회.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-eval-rag-140.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/eval-140-rag.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const DATASET_NAME = 'e2e-140-RAG시험'
const CASE_NAME = '검색 회귀'
const QUESTION = 'A/B 테스트에서 중요한 것은?'
const COLLECTION = 'Obsidian'
const CARD_LABEL = 'rag_hits_gte: 1' // 케이스 카드 태그 텍스트(arg 앞 공백 — Tag 렌더 `: ${a.arg}`)
const DETAIL_LABEL = 'rag_hits_gte:1' // 성적표 assert 상세 이름(공백 없음 — build_asserts f-string)

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

/** rows(활성 탭 내 DATASET_NAME 행들)의 innerText 중 predicate가 참인 게 하나라도 생길 때까지 폴링.
    RAG 검색만이라 real LLM 턴이 없어 137/138/139보다 훨씬 빠르지만, 백그라운드 순차 실행 큐 여유를
    위해 상한은 120초로 유지. */
async function pollFor(predicate, label, deadlineMs = 120000) {
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

  // ---------- 사전 정리(멱등화): 이전 실행 잔여 "e2e-140" 문제집이 있으면 먼저 삭제 ----------
  let preExisting = await dsRow().count()
  while (preExisting > 0) {
    await dsRow().first().getByRole('button').click()
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: '삭제' }).click()
    await page.waitForTimeout(600)
    preExisting = await dsRow().count()
  }
  console.log(`(사전정리) 잔여 "${DATASET_NAME}" 문제집 제거 완료(count=${preExisting})`)

  // ---------- 문제집 생성: 종류를 "RAG 컬렉션 시험"으로 변경 ----------
  await page.getByRole('button', { name: '새 문제집' }).click()
  await page.getByRole('dialog').getByText('새 문제집', { exact: true }).waitFor({ timeout: 5000 })
  const kindSelect = page.getByRole('dialog').locator('.ant-select').first()
  await kindSelect.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: 'RAG 컬렉션 시험' }).first().click()
  await page.waitForTimeout(200)
  await page.getByPlaceholder('이름 (예: 옵시디언 매니저 회귀 시험)').fill(DATASET_NAME)
  await page.getByRole('button', { name: '만들기' }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(500)

  // ---------- G1: 목록 행의 종류 태그가 "rag" ----------
  const kindTag = dsRow().locator('.ant-tag').filter({ hasText: 'rag' })
  const g1 = (await dsRow().count()) === 1 && (await kindTag.count()) > 0 && (await kindTag.first().innerText()) === 'rag'
  check(g1, `G1: 문제집 목록 "${DATASET_NAME}" 행의 종류 태그="rag"`)

  // ---------- 문제 추가: 기본 2기준 유지 + "채점 기준 추가"로 rag_hits_gte 기준 삽입 ----------
  await dsRow().first().click()
  await page.getByText(`문제집 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.getByRole('button', { name: '문제 추가' }).click()
  await page.waitForTimeout(300)
  await page.getByPlaceholder('문제 이름 (예: RAG 필수 회귀)').fill(CASE_NAME)
  await page.getByPlaceholder('에이전트에게 보낼 질문').fill(QUESTION)

  await page.getByRole('button', { name: '채점 기준 추가' }).click()
  await page.waitForTimeout(200)
  // 새로 추가된 3번째 기준 행의 유형 Select. 139(agent 문제집)는 기본값 라벨 "필수 도구/노드"로
  // hasText 매칭이 됐지만, RAG 문제집에서는 새로 마운트된 이 Select가 라벨 대신 원시값 "trace_has"를
  // 그대로 표시하는 실제 앱 렌더링 특이점을 발견(kind='rag' 드로어에서만 재현, agent 드로어는 정상 —
  // 옵션을 바꿔 선택하면 이후엔 라벨이 정상 표시됨). 앱 코드는 건드리지 않고, 라벨 문구 대신 폼
  // 컨테이너("채점 기준 추가" 버튼을 포함하는 가장 안쪽 div) 내 **마지막 Select**로 구조적으로
  // 특정한다(신규 행은 배열 끝에 추가되므로 항상 마지막).
  const addingForm = page.locator('div').filter({ hasText: '채점 기준 추가' }).last()
  const newAssertSelect = addingForm.locator('.ant-select').last()
  await newAssertSelect.waitFor({ timeout: 5000 })
  await newAssertSelect.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: 'RAG: 결과 N건 이상' }).first().click()
  await page.waitForTimeout(200)
  const argInput = page.getByPlaceholder('예: 2 — 검색 결과가 이 건수 이상(RAG 문제집 전용)')
  await argInput.waitFor({ timeout: 5000 })
  await argInput.fill('1')
  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(600)

  // ---------- G2: 케이스 카드 "3개 기준" + "rag_hits_gte: 1" 태그 ----------
  const caseCard = page.locator('div').filter({ hasText: CASE_NAME }).filter({ hasText: CARD_LABEL }).last()
  const g2Text = await caseCard.innerText().catch(() => '')
  const g2HasCount = /3개 기준/.test(g2Text)
  const g2HasLabel = g2Text.includes(CARD_LABEL)
  check(g2HasCount && g2HasLabel, `G2: "3개 기준"(${g2HasCount}) + "${CARD_LABEL}" 태그(${g2HasLabel}) [카드텍스트=${JSON.stringify(g2Text)}]`)

  // ---------- G3: 드로어 상단 Select placeholder = "시험 칠 RAG 컬렉션 선택" ----------
  const collectionSelect = page.locator('.ant-select').filter({ hasText: '시험 칠 RAG 컬렉션 선택' })
  const g3 = (await collectionSelect.count()) > 0
  check(g3, 'G3: 드로어 상단 Select placeholder="시험 칠 RAG 컬렉션 선택"')

  // ---------- "Obsidian" 컬렉션 선택 → 시험 실행 ----------
  await collectionSelect.first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-item-option', { hasText: COLLECTION }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '시험 실행' }).click()
  await page.getByText('시험 실행 시작', { exact: false }).first().waitFor({ timeout: 8000 }).catch(() => {})
  await page.getByRole('tab', { name: '실행 이력', selected: true }).waitFor({ timeout: 8000 }).catch(() => {})
  await closeDrawer()

  // ---------- G4: 실행 이력에 ok + 100% (1/1) + "RAG · Obsidian" 대상 (검색만이라 빠름 — 120초 폴링) ----------
  const targetLabel = `RAG · ${COLLECTION}`
  const run = await pollFor((t) => /ok/.test(t) && t.includes('100% (1/1)'), '런(ok)')
  const runOk = run.texts.some((t) => /ok/.test(t) && t.includes('100% (1/1)') && t.includes(targetLabel))
  check(runOk, `G4: 실행 이력 ok+100% (1/1)+"${targetLabel}" 대상 (텍스트=${JSON.stringify(run.texts)})`)

  // ---------- 성적표 드로어 열기 ----------
  await runRows().first().click()
  await page.getByText(`성적표 · ${DATASET_NAME}`, { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(500)

  // ---------- G5: 케이스 통과 + assert 상세에 "rag_hits_gte:1" 행 초록 체크 ----------
  const resultCard = page.locator('div').filter({ hasText: CASE_NAME }).filter({ hasText: DETAIL_LABEL }).last()
  const g5Text = await resultCard.innerText().catch(() => '')
  const g5HasPassTag = (await resultCard.locator('.ant-tag-green', { hasText: '통과' }).count()) > 0
  const g5HasDetailLine = g5Text.includes(DETAIL_LABEL)
  const detailRow = resultCard.locator('div').filter({ hasText: DETAIL_LABEL }).last()
  const g5HasCheckIcon = (await detailRow.locator('svg[data-icon="check-circle"]').count()) > 0
  check(
    g5HasPassTag && g5HasDetailLine && g5HasCheckIcon,
    `G5: 케이스 "통과" green 태그(${g5HasPassTag}) + assert 상세 "${DETAIL_LABEL}" 행(${g5HasDetailLine}) + 초록 체크아이콘(${g5HasCheckIcon}) [카드텍스트=${JSON.stringify(g5Text)}]`
  )

  // ---------- "관측" Collapse 펼침 ----------
  await resultCard.getByText('관측 (답변·흔적)', { exact: true }).click()
  await page.waitForTimeout(500)

  // ---------- G6: 유사도 태그(0.xxx)+근거 파일명 행 + 검색 결과 본문 텍스트 ----------
  const obsText = await resultCard.innerText().catch(() => '')
  const scoreTags = resultCard.locator('.ant-tag-geekblue')
  const scoreTexts = await scoreTags.allInnerTexts().catch(() => [])
  const g6aHasScoreTags = scoreTexts.length > 0
  const g6bScoreFormat = scoreTexts.every((t) => /^\d\.\d{3}$/.test(t))
  // 유사도 Tag의 DOM상 바로 다음 형제가 파일명 span(JSX: <Tag>{score}</Tag><span>{filename}</span>) —
  // "관측" 라벨 등 무관 텍스트가 섞이지 않게 형제 관계로 직접 특정.
  const filenameTexts = await scoreTags.evaluateAll((els) => els.map((el) => el.nextElementSibling?.textContent?.trim() ?? ''))
  const g6cHasFilenames = filenameTexts.length === scoreTexts.length && filenameTexts.every((t) => t.length > 0)
  const g6dHasBody = obsText.includes('문서 검색 결과')
  check(
    g6aHasScoreTags && g6bScoreFormat && g6cHasFilenames && g6dHasBody,
    `G6: 유사도 태그(개수=${scoreTexts.length}, 형식=${g6bScoreFormat}, 값=${JSON.stringify(scoreTexts)}) + 근거 파일명(${JSON.stringify(filenameTexts)}) + 검색 결과 본문(${g6dHasBody})`
  )

  // 사용자 UI/UX 확인용 스샷 — 관측 펼침 상태(유사도+근거 파일명+검색 결과 본문 표시).
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)

  // ---------- 정리: 성적표 드로어 닫고 문제집 삭제 → G7 ----------
  await closeDrawer()
  await openDatasetTab()
  await page.waitForTimeout(300)
  await dsRow().first().getByRole('button').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '삭제' }).click()
  await page.waitForTimeout(600)
  const remaining = await dsRow().count()
  check(remaining === 0, `G7: 정리 — 목록에서 "${DATASET_NAME}" 사라짐(잔여 행=${remaining})`)

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
