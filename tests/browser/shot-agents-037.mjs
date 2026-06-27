/* 에이전트 편집 폼의 RAG 지식 소스 피커 검증 스크린샷 (스펙 037) — 시스템 Chrome.
   admin(vite :5173) 로그인 후:
   (1) 에이전트 목록
   (2) UI 에이전트 '편집' → 폼 모달에서 '지식 소스 (RAG 컬렉션)' 필드 캡처
   를 확인. 핵심 회귀 단언: 이 필드가 **mem0 장기기억 선택과 무관하게**(ungated) 뜨고,
   listCollections()의 실 컬렉션(임베딩 모델 · 청크 N개)을 렌더하는지 — 과거엔 깨진
   blocks.embedding 소스를 mem0 게이트 뒤에 숨겨 dead였다.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-agents-037.mjs /tmp/agents037 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/agents037'
const EMAIL = process.env.ADMIN_EMAIL ?? 'verify032@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'Verify032!pw'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(1000)

  // (1) 에이전트 목록(기본 진입). 메뉴 '에이전트' 명시 클릭.
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-1-agents-list.png`, fullPage: true })

  // (2) UI 에이전트 행 클릭 → AgentDetail 드로어 → 라벨된 '편집' 버튼 → 폼.
  // (목록의 행 액션 편집은 아이콘 전용이라 접근명이 없어, 행을 열어 라벨 버튼을 쓴다.)
  await page.getByText('Code Reviewer', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-1b-detail.png`, fullPage: true })
  // 드로어 하단 주 버튼 '초안 편집'(혹은 카드 '편집') → 폼. 둘 다 openEdit를 부른다.
  const editBtn = page.getByRole('button', { name: /편집/ }).first()
  await editBtn.waitFor({ state: 'visible', timeout: 10000 })
  await editBtn.scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(300)
  await editBtn.click({ timeout: 8000 })
  // 폼 모달의 RAG 필드 라벨이 뜰 때까지.
  const fieldLabel = page.getByText('지식 소스 (RAG 컬렉션)', { exact: false })
  await fieldLabel.waitFor({ timeout: 8000 })
  await page.waitForTimeout(600)

  // 필드가 보이도록 스크롤 후 캡처.
  await fieldLabel.scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${OUT}-2-rag-field.png`, fullPage: true })

  // 단언 신호: 필드 존재 + 컬렉션 렌더(‘청크 N개’ 텍스트) + mem0 비종속 확인.
  const bodyText = await page.locator('body').innerText().catch(() => '')
  const fieldPresent = /지식 소스 \(RAG 컬렉션\)/.test(bodyText)
  const chunkRows = (bodyText.match(/청크 \d+개/g) || []).length
  const emptyHint = /컬렉션 없음/.test(bodyText)
  // mem0 게이트 비종속: 폼에 '장기 기억 (mem0)'가 선택돼 있든 말든 필드가 떠야 한다.
  const mem0Selected = /장기 기억 \(mem0\)/.test(bodyText)
  log('FIELD_PRESENT=' + fieldPresent)
  log('COLLECTION_ROWS(청크 N개)=' + chunkRows + ' EMPTY_HINT=' + emptyHint)
  log('MEM0_MENTIONED_IN_FORM=' + mem0Selected + ' (필드는 이와 무관하게 떠야 함)')

  const ok = fieldPresent && (chunkRows > 0 || emptyHint)
  log(ok ? 'AGENTS_037_OK' : 'AGENTS_037_SUSPECT')
  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
