/* 스펙 079 검증 — 인스펙터에 RAG 문서검색 · 메모리 조회 이력 노출. 시스템 Chrome(channel:'chrome').
   양성: Research Assistant(ui, mem0 장기 + docs_kb/product_titles RAG)로 한 턴 → 인스펙터에서
     ① 메모리 섹션 "회상 조회"(쿼리 «…» + N건 회상), ② "문서 검색 (RAG)" 섹션(컬렉션 태그) 노출.
   음성: Doc Translator(code, 단기만 · RAG 없음)로 한 턴 → 두 흔적 모두 숨김(무회귀).

   거짓초록 방지(learning 080·035): 셀렉터 0개=측정 실패. antd6 클래스는 stable한 텍스트/Tag로 짚는다.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-rag-memory-079.mjs /tmp/rag079 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/rag079'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

// 인스펙터 패널이 열렸는지(='턴 인스펙터' 헤더 존재).
async function ensureInspectorOpen() {
  if ((await page.getByText('턴 인스펙터', { exact: true }).count()) === 0) {
    await page.locator('button[title="인스펙터"]').first().click()
    await page.waitForTimeout(600)
  }
}

// 한 턴 전송 → 스트리밍 종료(=trace 칩 등장)까지 폴링 → 칩 클릭으로 턴 선택.
// 인스펙터를 먼저 열어 헤더 토글이 compact(아이콘만)가 되게 한다 → 화면에 보이는 '인스펙터'
// 텍스트는 trace 칩 뿐이라 칩 셀렉터가 헤더 버튼과 충돌하지 않는다(DebugChat: 인스펙터 열리면 항상 compact).
async function sendTurnAndSelect(text) {
  await ensureInspectorOpen()
  const ta = page.locator('textarea').first()
  await ta.fill(text)
  await ta.press('Enter')
  // 스트리밍 종료 신호 = trace 칩의 '인스펙터' 텍스트 등장(스트리밍 중엔 칩 미렌더).
  // RAG 턴은 mock LLM이 문서 전문을 통째로 스트리밍해 길다 → 최대 75s 폴링.
  let chipSeen = false
  for (let i = 0; i < 75; i++) {
    await page.waitForTimeout(1000)
    if ((await page.getByText(/^인스펙터/).count()) > 0) { chipSeen = true; break }
  }
  log('  CHIP_APPEARED=' + chipSeen)
  const chip = page.getByText(/^인스펙터/).last()
  if (await chip.count()) {
    await chip.click().catch(() => {})
    await page.waitForTimeout(600)
  }
}

try {
  // 1) 로그인 → Playground
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  log('STEP1_PLAYGROUND')

  // 2) 양성: Research Assistant(ui, mem0 + RAG)로 전환.
  const trigger = page.locator('button', { hasText: '(SDK)' }).first()
  if (await trigger.count()) await trigger.click()
  else await page.locator('header button, button:has-text("원격")').first().click()
  await page.waitForTimeout(500)
  const ra = page.locator('button', { hasText: 'Research Assistant' }).first()
  if (await ra.count()) { await ra.click(); log('STEP2_AGENT=Research Assistant') }
  else log('STEP2_AGENT_NOT_FOUND_FAIL')
  await page.waitForTimeout(800)

  await sendTurnAndSelect('product_titles 컬렉션에서 관련 문서를 찾아 요약해줘.')
  await page.screenshot({ path: `${OUT}-1-positive.png`, fullPage: true })

  // 검증(양성): 회상 조회 블록 + 문서 검색(RAG) 섹션. 컬렉션 태그는 .ant-tag로 스코프(채팅
  // 메시지에 'product_titles'가 들어가도 그건 .ant-tag가 아니므로 오탐 배제). search_documents=RAG 호출 카드.
  const memQueryPos = await page.getByText('회상 조회', { exact: true }).count()
  const recallTag = await page.getByText(/건 회상/).count()
  const ragSectionPos = await page.getByText('문서 검색 (RAG)', { exact: false }).count()
  const ragColTagPos = await page.locator('.ant-tag', { hasText: /docs_kb|product_titles/ }).count()
  const ragCallCard = await page.getByText('search_documents', { exact: true }).count()
  log('POS_MEM_QUERY=' + memQueryPos + ' (expect >=1)')
  log('POS_RECALL_TAG=' + recallTag + ' (expect >=1)')
  log('POS_RAG_SECTION=' + ragSectionPos + ' (expect >=1)')
  log('POS_RAG_COLLECTION_TAG=' + ragColTagPos + ' (expect >=1)')
  log('POS_RAG_CALL_CARD(search_documents)=' + ragCallCard + ' (expect >=1 — RAG 도구 호출 시)')

  // 3) 음성: Doc Translator(code, 단기·RAG 없음)로 전환 후 한 턴.
  await page.getByRole('button', { name: '새 대화' }).first().click().catch(() => {})
  await page.waitForTimeout(600)
  // AgentCombo 트리거 = 현재 에이전트명을 안은 헤더 버튼. 열고 Doc Translator 선택.
  await page.locator('button', { hasText: 'Research Assistant' }).first().click().catch(() => {})
  await page.waitForTimeout(600)
  const dt = page.locator('button', { hasText: 'Doc Translator' }).first()
  if (await dt.count()) { await dt.click(); log('STEP3_AGENT=Doc Translator') }
  else log('STEP3_AGENT_NOT_FOUND_FAIL')
  await page.waitForTimeout(800)

  await sendTurnAndSelect('Translate this sentence to Korean: hello world.')
  await page.screenshot({ path: `${OUT}-2-negative.png`, fullPage: true })

  // 검증(음성): 두 흔적 모두 숨김. (MCP 섹션 자체는 남을 수 있으나 RAG/회상 흔적은 0.)
  const memQueryNeg = await page.getByText('회상 조회', { exact: true }).count()
  const ragSectionNeg = await page.getByText('문서 검색 (RAG)', { exact: false }).count()
  log('NEG_MEM_QUERY=' + memQueryNeg + ' (expect 0)')
  log('NEG_RAG_SECTION=' + ragSectionNeg + ' (expect 0)')

  // 종합 판정.
  const pass = memQueryPos >= 1 && recallTag >= 1 && ragSectionPos >= 1 && ragColTagPos >= 1
    && memQueryNeg === 0 && ragSectionNeg === 0
  log(pass ? 'RAG079_PASS' : 'RAG079_FAIL')
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
  else log('NO_CONSOLE_ERRORS')
} catch (e) {
  log('RAG079_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png`, fullPage: true }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
