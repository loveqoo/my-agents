/* 스펙 130 e2e — 조율형(옵시디언 매니저)의 브로커 경유 RAG 검색이 인스펙터에 표면화되는지,
   사용자 실사용 시나리오 그대로(시드 불필요·실 에이전트·실 컬렉션). 시스템 Chrome.

   조율형은 로컬 LLM(qwen3.6-35b)으로 분석→계획→위임→종합을 돌아 응답까지 60~120초 걸릴 수 있다 —
   고정 대기 대신 인스펙터 트리거("인스펙터" 텍스트, trace 도착 후에만 렌더)가 뜰 때까지 폴링한다.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-broker-rag-inspector-130.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/broker-rag-130.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const AGENT = '옵시디언 매니저'
const QUESTION = 'A/B 테스트에서 중요한 것은?'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()

// chat SSE 응답을 가로채 session id를 뽑는다(스펙 129/122류 UI 셀렉터 대신, 네트워크 바디의
// `data: {"session":"..."}` 프레임 — admin/src/api.ts handleFrame과 동일한 포맷).
let sessionId = null
page.on('response', async (resp) => {
  try {
    if (resp.request().method() !== 'POST') return
    if (!/\/agents\/.+\/chat$/.test(resp.url())) return
    const text = await resp.text()
    const m = text.match(/"session":\s*"([^"]+)"/)
    if (m) sessionId = m[1]
  } catch { /* 스트림 취소·타이밍 경합은 무시 — 세션 id는 폴백으로도 로그에 남는다 */ }
})

// 에이전트 스위처(아바타 있는 버튼)를 열고 이름으로 선택(shot-override-by-kind-122.mjs 패턴).
async function selectAgent(name) {
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(name, { exact: false }).first().click()
  await page.waitForTimeout(500)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 1: Playground 진입.
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  check(true, '1: Playground 진입')

  // 2: 에이전트 스위처로 "옵시디언 매니저" 선택.
  await selectAgent(AGENT)
  const headerHasAgent = await page.getByText(AGENT, { exact: true }).first().isVisible().catch(() => false)
  check(headerHasAgent, `2: 에이전트 스위처로 "${AGENT}" 선택`)

  // 3: 채팅 입력창에 질문 전송.
  const box = page.locator('textarea').first()
  await box.click()
  await box.fill(QUESTION)
  await page.waitForTimeout(200)
  await box.press('Enter')
  console.log(`  --  전송: ${QUESTION}`)

  // 응답 도착 대기 — 헤더 토글 버튼("인스펙터")·우측 패널 제목("턴 인스펙터")은 항상 떠 있어
  // 오탐지되므로, 트레이스 도착 후에만 렌더되는 메시지 트레이스 칩(DebugChat.tsx Chip — "N mem")을
  // 최대 180초 폴링(고정 대기 대신 실제 완료 신호).
  const traceChip = page.getByText(/\d+\s*mem/).last()
  const arrived = await traceChip.waitFor({ state: 'visible', timeout: 180000 }).then(() => true).catch(() => false)
  check(arrived, '3: 응답 도착(트레이스 수신 — 메시지 트레이스 칩 표시, 최대 180초 대기)')

  // 4: 그 AI 메시지의 트레이스 칩(클릭이 부모 TraceChips onClick으로 버블)을 클릭해 인스펙터를 연다.
  if (arrived) await traceChip.click({ timeout: 8000 })
  await page.waitForTimeout(500)

  const bodyText = await page.locator('#root').innerText().catch(() => '')

  // R1: 인스펙터에 "문서 검색 (RAG)" 섹션 존재.
  const r1 = /문서 검색 \(RAG\)/.test(bodyText)
  check(r1, 'R1: 인스펙터에 "문서 검색 (RAG)" 섹션 존재')

  // R2: 그 안에 "rag:Obsidian" 태그 표시.
  const r2 = /rag:Obsidian/.test(bodyText)
  check(r2, 'R2: "rag:Obsidian" 태그 표시')

  // R3: "검색 N건"(N≥1) + "최고 유사도 0.NNN" 텍스트 표시.
  const hitsMatch = bodyText.match(/검색\s*(\d+)건/)
  const scoreMatch = bodyText.match(/최고 유사도\s*(\d\.\d+)/)
  const hits = hitsMatch ? parseInt(hitsMatch[1], 10) : 0
  const r3 = hits >= 1 && !!scoreMatch
  check(r3, `R3: "검색 N건"(N≥1) + "최고 유사도 0.NNN" 표시(실측: 검색 ${hits}건, 유사도 ${scoreMatch ? scoreMatch[1] : '없음'})`)

  // R6: 메시지 트레이스 칩에 rag 카운트 표시(스펙 130 확장 — mem·mcp만 있던 칩에 rag 추가).
  const chipRag = bodyText.match(/(\d+)\s*rag/)
  check(!!chipRag && Number(chipRag[1]) >= 1, `R6: 트레이스 칩에 "N rag"(N≥1) 표시(실측: ${chipRag ? chipRag[1] : '없음'})`)

  // R4(참고): 응답 본문에 노트 내용 반영 흔적. 모델 비결정 — FAIL이어도 R1~R3 ok면 전체 PASS.
  const r4 = /문해력|반응 패턴|A\/B/.test(bodyText)
  console.log((r4 ? '  ok  ' : ' note ') + 'R4(참고): 응답 본문에 노트 내용 반영 흔적(문해력/반응 패턴/A·B)')

  // R5: 화면에 sk- 시작 6자+ 토큰 없음.
  const secretLeak = /sk-[A-Za-z0-9_-]{6,}/.test(bodyText)
  const r5 = !secretLeak
  check(r5, 'R5: 화면에 sk- 시작 6자+ 토큰 없음')

  // 6: 스크린샷(인스펙터 RAG 섹션 보이게).
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('shot:', OUT)

  console.log('session_id:', sessionId ?? '(네트워크 프레임에서 미검출 — 세션 목록에서 확인 필요)')
  console.log(`question: "${QUESTION}"`)
} catch (e) {
  console.error('ERR', e.message)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
