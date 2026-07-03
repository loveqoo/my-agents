/* 스펙 134 e2e — 턴 트레이스에 적용 오버라이드 기록. 템플릿=shot-broker-rag-inspector-130.mjs
   (로그인·에이전트 선택·트레이스 칩 대기·인스펙터 열기)+ shot-inspector-detail-131.mjs D6(새로고침 후
   세션 재선택 — 꼬리 12자 매칭). 시스템 Chrome.

   시나리오: 오버라이드(temperature) 적용 → 전송 → 인스펙터 "오버라이드 (이 턴 적용)" 섹션 확인(O1) →
   새로고침 후 같은 세션 재선택해도 표시(O2, trace JSONB 영속) → 오버라이드 재적용 후 과거 세션 선택 시
   안내 토스트(O3) → 오버라이드 해제 후 새 턴은 오버라이드 섹션 없음(O4) → 비밀 미노출(O5).

   조율형(옵시디언 매니저)은 로컬 LLM 분석→계획→위임→종합을 돌아 응답까지 60~120초 걸릴 수 있다 —
   고정 대기 대신 트레이스 칩(/\d+\s*mem/) 폴링(최대 180초).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-override-trace-134.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/override-trace-134.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const AGENT = '옵시디언 매니저'
const GREETING = '안녕'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()

// chat SSE 응답을 가로채 session id를 뽑는다(130/131 패턴 — admin/src/api.ts handleFrame과 동일 포맷).
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

// 에이전트 스위처(아바타 있는 버튼)를 열고 이름으로 선택(122 패턴).
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

// 메시지 전송 후 트레이스 칩(N mem) 도착까지 최대 180초 폴링 → 클릭해 인스펙터를 연다.
async function sendAndOpenInspector(text) {
  const box = page.locator('textarea').first()
  await box.click()
  await box.fill(text)
  await page.waitForTimeout(200)
  await box.press('Enter')
  console.log(`  --  전송: ${text}`)
  const traceChip = page.getByText(/\d+\s*mem/).last()
  const arrived = await traceChip.waitFor({ state: 'visible', timeout: 180000 }).then(() => true).catch(() => false)
  if (arrived) await traceChip.click({ timeout: 8000 })
  await page.waitForTimeout(500)
  return arrived
}

// 오버라이드 드로어를 열고 temperature 스위치를 켠 뒤 슬라이더 값을 기본(0.7)에서 이동, "적용".
// 반환: 적용된 temperature 값 텍스트(스크린 표시치).
async function applyTemperatureOverride() {
  const ovBtn = page.locator('button[title*="오버라이드"]').first()
  await ovBtn.click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')

  // "세부 설정 (선택)" Collapse를 펼친다(temperature는 기본 접힘).
  const advToggle = drawer.getByText('세부 설정 (선택)', { exact: false }).first()
  await advToggle.click()
  await page.waitForTimeout(300)

  const tempGroup = drawer.locator('[role="group"][aria-label="Temperature"]')
  await tempGroup.locator('.ant-switch').click()
  await page.waitForTimeout(300)

  // 슬라이더 핸들 포커스 후 화살표로 기본값(0.7)에서 이동(드래그 좌표 의존 대신 키보드 — 안정적).
  const handle = tempGroup.locator('.ant-slider-handle')
  await handle.click({ force: true })
  await page.waitForTimeout(150)
  for (let i = 0; i < 3; i++) {
    await handle.press('ArrowRight')
    await page.waitForTimeout(80)
  }
  const valueText = (await tempGroup.locator('span').last().textContent())?.trim() ?? ''

  await drawer.getByRole('button', { name: '적용 (새 대화)' }).click()
  await page.waitForTimeout(800)
  return valueText
}

// 오버라이드 드로어를 열고 "오버라이드 해제" 클릭(새 대화로 리셋).
async function clearOverride() {
  const ovBtn = page.locator('button[title*="오버라이드"]').first()
  await ovBtn.click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')
  await drawer.getByRole('button', { name: '오버라이드 해제' }).click()
  await page.waitForTimeout(800)
}

// 세션 스위처를 열고 sid 꼬리 12자로 그 세션을 선택(131 D6 패턴).
async function pickSessionByIdTail(sid) {
  const sessionBtn = page.locator('button[title^="세션 — 과거 대화"]')
  const visible = await sessionBtn.isVisible().catch(() => false)
  if (!visible) return { picked: false, note: '헤더 세션 스위처 버튼을 찾지 못함' }
  await sessionBtn.click({ timeout: 8000 })
  await page.waitForTimeout(700)
  const pickerText = await page.locator('body').innerText()
  const idTail = sid && sid.length > 14 ? sid.slice(-12) : sid
  if (!idTail || !pickerText.includes(idTail)) {
    return { picked: false, note: `세션 id 꼬리(${idTail})가 피커 목록에서 발견되지 않음` }
  }
  await page.getByText(idTail, { exact: false }).last().click({ timeout: 8000 })
  await page.waitForTimeout(1200)
  return { picked: true, note: `id 꼬리 ${idTail} 매칭` }
}

let firstSessionId = null

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

  // 2: 오버라이드(temperature) 적용.
  const tempVal1 = await applyTemperatureOverride()
  console.log(`  --  temperature 오버라이드 적용값(화면 표시): ${tempVal1}`)
  check(!!tempVal1 && tempVal1 !== '—', '2: temperature 오버라이드 적용(기본 자동 아님)')

  // 3: 채팅 전송 → 트레이스 칩 대기 → 인스펙터 열기.
  const arrived1 = await sendAndOpenInspector(GREETING)
  check(arrived1, '3: 응답 도착(트레이스 수신, 최대 180초 대기)')

  let bodyText = await page.locator('#root').innerText().catch(() => '')

  // O1: 인스펙터에 "오버라이드 (이 턴 적용)" 섹션 + "temperature" 키/값 표시.
  const hasSection1 = /오버라이드 \(이 턴 적용\)/.test(bodyText)
  const hasTempKey1 = /temperature/.test(bodyText)
  const o1 = hasSection1 && hasTempKey1
  check(o1, `O1: 인스펙터에 "오버라이드 (이 턴 적용)" 섹션 + temperature 키/값 표시(섹션=${hasSection1}, temperature키=${hasTempKey1})`)

  // O5: 화면에 sk- 시작 6자+ 토큰 없음.
  const secretLeak1 = /sk-[A-Za-z0-9_-]{6,}/.test(bodyText)
  const o5 = !secretLeak1
  check(o5, 'O5: 화면에 sk- 시작 6자+ 토큰 없음')

  // O1 상태 스크린샷(오버라이드 섹션 보이게).
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('shot(O1):', OUT)

  firstSessionId = sessionId
  console.log('session_id(첫 턴):', firstSessionId ?? '(네트워크 프레임에서 미검출)')

  // O2: 새로고침 → Playground 재진입 → 에이전트 재선택 → 세션 스위처로 방금 세션 재선택 →
  // 그 턴 칩 클릭 → O1 섹션 여전히 표시(trace JSONB 영속).
  let o2 = false
  let o2Note = ''
  try {
    await page.reload({ waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(1000)
    const onPlayground = await page.locator('textarea').first().isVisible().catch(() => false)
    if (!onPlayground) await gotoPlayground()
    await selectAgent(AGENT)
    await page.waitForTimeout(500)

    const pick1 = await pickSessionByIdTail(firstSessionId)
    if (!pick1.picked) {
      o2Note = pick1.note
    } else {
      const chip = page.getByText(/\d+\s*mem/).last()
      const chipVisible = await chip.isVisible().catch(() => false)
      if (chipVisible) {
        await chip.click({ timeout: 8000 })
        await page.waitForTimeout(500)
        const bodyText2 = await page.locator('#root').innerText().catch(() => '')
        o2 = /오버라이드 \(이 턴 적용\)/.test(bodyText2) && /temperature/.test(bodyText2)
        o2Note = `복원 후 섹션 표시=${o2}(${pick1.note})`
      } else {
        o2Note = '복원된 세션에서 트레이스 칩(N mem)을 찾지 못함'
      }
    }
  } catch (e) {
    o2Note = '예외: ' + e.message
  }
  check(o2, `O2: 새로고침 후 세션 재선택 → 오버라이드 섹션 영속(${o2Note})`)
  await page.screenshot({ path: '/tmp/override-trace-134-o2.png', fullPage: false }).catch(() => {})

  // O3: reload 후 오버라이드는 풀린 상태 — 다시 적용 → 세션 스위처로 아까 그 과거 세션 선택 →
  // message.info 토스트 표시 확인.
  let o3 = false
  let o3Note = ''
  try {
    const tempVal2 = await applyTemperatureOverride()
    o3Note = `재적용값=${tempVal2} · `
    const pick2 = await pickSessionByIdTail(firstSessionId)
    if (!pick2.picked) {
      o3Note += pick2.note
    } else {
      const toastVisible = await page.locator('.ant-message-notice').first().waitFor({ timeout: 6000 }).then(() => true).catch(() => false)
      let toastText = ''
      if (toastVisible) {
        await page.waitForTimeout(200)
        toastText = (await page.locator('.ant-message-notice').first().textContent())?.trim() ?? ''
      }
      o3 = toastVisible && /오버라이드 적용 중/.test(toastText) && /이전 턴들과 설정이 다를 수/.test(toastText)
      o3Note += `토스트 노출=${toastVisible}, 텍스트="${toastText}"`
    }
  } catch (e) {
    o3Note += '예외: ' + e.message
  }
  check(o3, `O3: 과거 세션 로드 시 오버라이드 안내 토스트(${o3Note})`)
  await page.screenshot({ path: '/tmp/override-trace-134-o3.png', fullPage: false }).catch(() => {})

  // O4: 오버라이드 해제 후 새 턴 전송 → 그 턴 인스펙터에 "오버라이드" 섹션 없음(미적용 턴 무회귀).
  let o4 = false
  let o4Note = ''
  try {
    await clearOverride()
    const arrived2 = await sendAndOpenInspector(GREETING)
    if (!arrived2) {
      o4Note = '두 번째 턴 응답 미도착(트레이스 칩 타임아웃)'
    } else {
      const bodyText4 = await page.locator('#root').innerText().catch(() => '')
      const noSection = !/오버라이드 \(이 턴 적용\)/.test(bodyText4)
      o4 = noSection
      o4Note = `섹션 없음=${noSection}`
      // O5 재확인(두 번째 턴 화면에서도 비밀 미노출).
      const secretLeak2 = /sk-[A-Za-z0-9_-]{6,}/.test(bodyText4)
      check(!secretLeak2, 'O5(재확인): 두 번째 턴 화면에도 sk- 토큰 없음')
    }
  } catch (e) {
    o4Note = '예외: ' + e.message
  }
  check(o4, `O4: 오버라이드 해제 후 새 턴 — 인스펙터에 오버라이드 섹션 없음(${o4Note})`)
  await page.screenshot({ path: '/tmp/override-trace-134-o4.png', fullPage: false }).catch(() => {})

  console.log('session_id(첫 턴, 미삭제):', firstSessionId ?? '(미검출)')
  console.log('session_id(네 번째 턴, 미삭제):', sessionId ?? '(미검출)')
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
