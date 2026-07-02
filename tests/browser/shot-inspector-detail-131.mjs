/* 스펙 131 e2e — 인스펙터 상세화(전송 프롬프트 전문·도구 결과 본문·노드 값)가 실제 화면에
   표면화되는지. 템플릿=shot-broker-rag-inspector-130.mjs(로그인·에이전트 선택·질문 전송·트레이스 칩
   대기·인스펙터 열기는 그대로 재사용 — 130이 안정 통과 중인 경로).

   조율형(옵시디언 매니저)은 로컬 LLM 분석→계획→위임→종합을 돌아 응답까지 60~120초 걸릴 수 있다 —
   고정 대기 대신 트레이스 칩(/\d+\s*mem/) 폴링.

   D1~D5: 첫 대화 직후 인스펙터에서 확인.
   D6: 새로고침(page.reload) 후 같은 세션을 다시 골라 트레이스가 영속 복원되는지 확인.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-inspector-detail-131.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/inspector-131.png'
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

// chat SSE 응답을 가로채 session id를 뽑는다(130 패턴 재사용 — admin/src/api.ts handleFrame과 동일 포맷).
let sessionId = null
page.on('response', async (resp) => {
  try {
    if (resp.request().method() !== 'POST') return
    if (!/\/agents\/.+\/chat$/.test(resp.url())) return
    const text = await resp.text()
    const m = text.match(/"session":\s*"([^"]+)"/)
    if (m) sessionId = m[1]
  } catch { /* 스트림 취소·타이밍 경합은 무시 */ }
})

// 에이전트 스위처(아바타 있는 버튼)를 열고 이름으로 선택(shot-override-by-kind-122.mjs 패턴).
async function selectAgent(name) {
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(name, { exact: false }).first().click()
  await page.waitForTimeout(500)
}

async function gotoPlayground() {
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 1: Playground 진입 + 에이전트 선택.
  await gotoPlayground()
  await selectAgent(AGENT)
  const headerHasAgent = await page.getByText(AGENT, { exact: true }).first().isVisible().catch(() => false)
  check(headerHasAgent, `1: Playground 진입 + 에이전트 "${AGENT}" 선택`)

  // 2: 채팅 입력창에 질문 전송.
  const box = page.locator('textarea').first()
  await box.click()
  await box.fill(QUESTION)
  await page.waitForTimeout(200)
  await box.press('Enter')
  console.log(`  --  전송: ${QUESTION}`)

  // 응답 도착 대기 — 메시지 트레이스 칩(DebugChat.tsx Chip — "N mem")을 최대 180초 폴링.
  const traceChip = page.getByText(/\d+\s*mem/).last()
  const arrived = await traceChip.waitFor({ state: 'visible', timeout: 180000 }).then(() => true).catch(() => false)
  check(arrived, '2: 응답 도착(트레이스 수신 — 메시지 트레이스 칩 표시, 최대 180초 대기)')

  // 3: 그 AI 메시지의 트레이스 칩(클릭이 부모 TraceChips onClick으로 버블)을 클릭해 인스펙터를 연다.
  if (arrived) await traceChip.click({ timeout: 8000 })
  await page.waitForTimeout(500)

  let bodyText = await page.locator('#root').innerText().catch(() => '')

  // D1: "전송 프롬프트" 섹션 존재(구 "시스템 프롬프트" 섹션 대체 — sentMessages 있는 새 턴).
  const d1 = /전송 프롬프트/.test(bodyText) && !/^시스템 프롬프트$/m.test(bodyText)
  check(d1, 'D1: "전송 프롬프트" 섹션 존재(구 "시스템 프롬프트" 미표시)')

  // D2: 그 안 Collapse에 role 태그 "system"/"user" 표시 + system 패널(기본 펼침)에 페르소나
  // 텍스트 일부("Friendly") + 메시지 수 카운트(Section 헤더 Tag) 표시.
  // role 태그는 antd Tag 뒤에 글자수(예: "system88자")가 공백 없이 바로 붙어 렌더되므로
  // \b(단어 경계) 대신 태그 뒤 숫자로 경계를 잡는다(실측: "system88자", "user17자").
  const roleTagsOk = /\bsystem\d/.test(bodyText) && /\buser\d/.test(bodyText)
  const personaOk = /Friendly/.test(bodyText)
  // 메시지 수 카운트: "전송 프롬프트" 옆 Tag 배지(예: "전송 프롬프트" 다음 줄에 숫자만 있는 Tag) —
  // Section 컴포넌트가 title 옆에 count Tag를 렌더하므로 "전송 프롬프트\n2" 류 패턴으로 확인.
  const countMatch = bodyText.match(/전송 프롬프트\s*\n?\s*(\d+)/)
  const countOk = !!countMatch && Number(countMatch[1]) >= 2
  check(roleTagsOk, 'D2a: role 태그 "system"/"user" 표시')
  check(personaOk, 'D2b: system 패널에 페르소나 텍스트("Friendly") 표시')
  check(countOk, `D2c: 메시지 수 카운트 표시(실측: ${countMatch ? countMatch[1] : '없음'})`)
  const d2 = roleTagsOk && personaOk && countOk

  // D3: "문서 검색 (RAG)" 섹션의 브로커 행 아래 "검색 결과 본문" Collapse 존재 → 클릭 →
  // "[문서 검색 결과" 텍스트와 "유사도" 표시(실 스니펫).
  const ragSectionOk = /문서 검색 \(RAG\)/.test(bodyText)
  const resultToggle = page.getByText('검색 결과 본문', { exact: false }).first()
  const toggleVisible = await resultToggle.isVisible().catch(() => false)
  if (toggleVisible) {
    await resultToggle.click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(400)
  }
  bodyText = await page.locator('#root').innerText().catch(() => '')
  const d3 = ragSectionOk && toggleVisible && /\[문서 검색 결과/.test(bodyText) && /유사도/.test(bodyText)
  check(d3, `D3: RAG 섹션 "검색 결과 본문" 펼침 → "[문서 검색 결과"+"유사도" 표시(rag섹션=${ragSectionOk}, 토글노출=${toggleVisible})`)

  // D4: "LangGraph 경로" 섹션에서 "query:" 뒤에 실제 질문 텍스트(가림 아님). "delegated:"는 카운트만.
  const queryMatch = bodyText.match(/query:\s*([^\n]{1,120})/)
  const queryVal = queryMatch ? queryMatch[1].trim() : ''
  const queryMasked = /^<\d+자>/.test(queryVal)
  const d4 = !!queryMatch && !queryMasked && queryVal.length > 0
  check(d4, `D4: "query:" 뒤 실값 표시(가림 아님) — 실측: "${queryVal.slice(0, 60)}"`)
  const delegatedMatch = bodyText.match(/delegated:\s*([^\n]{1,120})/)
  console.log(`  --  참고: delegated 값 프리뷰 여부 = ${delegatedMatch ? !/^<\d+자>/.test(delegatedMatch[1].trim()) : '(delegated 키 없음)'}`)

  // D5: 화면에 sk- 시작 6자+ 토큰 없음.
  const secretLeak = /sk-[A-Za-z0-9_-]{6,}/.test(bodyText)
  const d5 = !secretLeak
  check(d5, 'D5: 화면에 sk- 시작 6자+ 토큰 없음')

  // 스크린샷: 전송 프롬프트 + RAG 본문 펼친 상태.
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('shot:', OUT)
  console.log('session_id:', sessionId ?? '(네트워크 프레임에서 미검출)')
  console.log(`question: "${QUESTION}"`)

  // D6(영속 확인): 페이지 새로고침 → 같은 세션 재선택 → 이전 턴 트레이스 칩 클릭 →
  // D1(전송 프롬프트 섹션)·D4(query 실값)가 여전히 보이는지(trace JSONB 영속·재로드 복원).
  let d6 = false
  let d6Note = ''
  try {
    await page.reload({ waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(1000)
    // 새로고침 후 랜딩이 Playground가 아닐 수 있음 — 메뉴로 다시 진입.
    const onPlayground = await page.locator('textarea').first().isVisible().catch(() => false)
    if (!onPlayground) await gotoPlayground()
    await selectAgent(AGENT)
    await page.waitForTimeout(500)

    // 세션 스위처(헤더 세션칩)를 열고 방금 생성된 세션 id로 선택(shot-resume-session-055.mjs 패턴).
    const sessionBtn = page.locator('button[title^="세션 — 과거 대화"]')
    const sessionBtnVisible = await sessionBtn.isVisible().catch(() => false)
    await page.screenshot({ path: '/tmp/inspector-131-d6-before-picker.png', fullPage: false }).catch(() => {})
    if (sessionBtnVisible) {
      await sessionBtn.click({ timeout: 8000 })
      await page.waitForTimeout(800)
      await page.screenshot({ path: '/tmp/inspector-131-d6-picker-open.png', fullPage: false }).catch(() => {})
      const pickerText = await page.locator('body').innerText()
      // 피커 행은 전체 session id가 아니라 꼬리 12자만 "…"+slice(-12)로 렌더된다
      // (DebugChat.tsx) — 전체 id로 찾으면 항상 미검출이므로 같은 규칙으로 꼬리를 잘라 매칭.
      const idTail = sessionId && sessionId.length > 14 ? sessionId.slice(-12) : sessionId
      if (idTail && pickerText.includes(idTail)) {
        await page.getByText(idTail, { exact: false }).last().click({ timeout: 8000 })
        await page.waitForTimeout(1500)
      } else {
        d6Note = `세션 id 꼬리(${idTail})가 피커 목록에서 발견되지 않음`
      }
    } else {
      d6Note = '헤더 세션 스위처 버튼을 찾지 못함'
    }

    if (!d6Note) {
      // 이전 턴 트레이스 칩 클릭.
      const chip2 = page.getByText(/\d+\s*mem/).last()
      const chip2Visible = await chip2.isVisible().catch(() => false)
      if (chip2Visible) {
        await chip2.click({ timeout: 8000 })
        await page.waitForTimeout(500)
        const bodyText2 = await page.locator('#root').innerText().catch(() => '')
        const d1r = /전송 프롬프트/.test(bodyText2)
        const q2 = bodyText2.match(/query:\s*([^\n]{1,120})/)
        const d4r = !!q2 && !/^<\d+자>/.test((q2[1] || '').trim())
        d6 = d1r && d4r
        d6Note = `복원 후 D1=${d1r} D4=${d4r}(query="${q2 ? q2[1].trim().slice(0, 50) : ''}")`
      } else {
        d6Note = '복원된 세션에서 트레이스 칩(N mem)을 찾지 못함'
      }
    }
  } catch (e) {
    d6Note = '예외: ' + e.message
  }
  check(d6, `D6: 새로고침 후 세션 재선택 → 트레이스 영속 확인(${d6Note})`)
  await page.screenshot({ path: '/tmp/inspector-131-d6-after.png', fullPage: false }).catch(() => {})
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
