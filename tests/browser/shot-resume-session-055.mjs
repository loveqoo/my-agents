/* 스펙 055 — Playground 세션 이어가기 E2E (시스템 Chrome).
   사용자 시나리오의 일반화: 위험 도구 승인하러 다른 뷰로 갔다 오면 Playground가 초기화된다.
   → 과거 세션을 피커로 골라 대화를 복원하고 이어서 보낼 수 있어야 한다.

   mock LLM은 도구 호출 미지원(mock_remote.py)이라 delete_record를 채팅으로 발화시킬 수 없다.
   그래서 '리셋'은 동일하게 발생하는 **뷰 이동(언마운트)**으로 재현한다 — 새 코드(세션 피커·
   getSessionMessages 로드·같은 session_id 이어가기·백엔드 agent_id 필터)는 도구와 무관하게
   영속 세션을 읽으므로 본 시나리오가 핵심 경로 전체를 행사한다. 승인 후 resume_approval의
   세션 영속은 스펙 041이 커버.

   단계:
   (1) Playground에서 고유 마커 메시지 전송 → mock 응답 → 세션 생성(헤더 세션칩에 sess- 표시).
   (2) 메뉴 '승인'으로 이동 후 'Playground'로 복귀 → 대화 소실(리셋 재현, 세션칩 '새 세션').
   (3) 세션 피커 열기 → 방금 세션 선택 → 마커 메시지가 대화에 복원되는지.
   (4) 한 마디 더 전송 → 같은 세션에 이어지는지(말풍선 증가).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-resume-session-055.mjs /tmp/resume055 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/resume055'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const MARKER = 'RESUME055-마커-' + (process.env.MARKER_SUFFIX ?? 'aZ')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

const gotoPlayground = async () => {
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // (1) Playground → 마커 메시지 전송. @ant-design/x Sender는 textarea — 포커스 유지를 위해
  // page.keyboard가 아니라 요소에 직접 press('Enter')해야 controlled 전송이 발화한다(032 패턴).
  await gotoPlayground()
  const ta = page.locator('textarea').first()
  await ta.waitFor({ timeout: 8000 })
  await ta.fill(MARKER)
  await ta.press('Enter')
  // 헤더 세션칩에 sess- 가 뜰 때까지 대기(세션 생성).
  const chipBtn = page.locator('button[title^="세션 — 과거 대화"]')
  await page.getByText(/sess-/).first().waitFor({ timeout: 12000 }).catch(() => {})
  // 스트리밍 완료까지 대기 — 이게 끝나야 백엔드 _persist가 일어난다. 일찍 이탈하면 턴이
  // 중단돼 영속 안 됨. textarea 다시 활성(전송 후 비워짐) + 넉넉한 여유로 완료를 보장한다.
  await page.waitForTimeout(9000)
  await page.screenshot({ path: `${OUT}-1-after-send.png`, fullPage: true })
  const bodyText1 = await page.locator('body').innerText()
  // createdSid는 헤더 칩에서 정확히(시드 세션 id 오염 방지).
  const chipText = (await chipBtn.innerText().catch(() => '')) || ''
  const chipMatch = chipText.match(/sess-[0-9a-f]{6,}/)
  const createdSid = chipMatch ? chipMatch[0] : null
  log('STEP1: created_session=' + createdSid + ' marker_in_chat=' + bodyText1.includes(MARKER))

  // (2) 다른 뷰로 이동(언마운트) 후 복귀 → 리셋 재현. '개요'로 이탈(항상 존재·클릭 안정).
  await page.getByText('개요', { exact: true }).first().click()
  await page.waitForTimeout(900)
  await gotoPlayground()
  const afterReset = await page.locator('body').innerText()
  const resetOk = !afterReset.includes(MARKER) // 대화 소실 = 리셋 재현
  log('STEP2: reset_reproduced(대화 소실)=' + resetOk)
  await page.screenshot({ path: `${OUT}-2-after-reset.png`, fullPage: true })

  // (3) 세션 피커 열기 → 방금 세션 선택 → 마커 복원.
  // 세션칩 버튼: comment 아이콘 + '새 세션'/sess- 라벨. title로 특정.
  const sessionBtn = page.locator('button[title^="세션 — 과거 대화"]')
  await sessionBtn.click({ timeout: 8000 })
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-3-picker-open.png`, fullPage: true })
  // 생성된 세션이 드롭다운에 실제로 떴는지(백엔드 agent_id 필터가 이 에이전트 세션을 반환).
  const pickerText = await page.locator('body').innerText()
  const createdInPicker = createdSid ? pickerText.includes(createdSid) : false
  // 리셋 후 채팅은 비어 있으므로(STEP2), 드롭다운에 마커 텍스트가 보이면 그건 세션 preview
  // 라벨(첫 사용자 메시지)이다 — '해시코드만 보여 불편' 피드백 해소 검증.
  const previewLabelOk = pickerText.includes(MARKER)
  // 부정 단언(learning 057): 피커에 떠 있는 *모든* 행이 사람이 읽는 형식이어야 한다 —
  // 대상(marker) 행만 보지 말 것. 시드/레거시 세션이 같은 드롭다운에서 raw ISO 타임스탬프
  // (…+00:00)로 깨져 보이던 회귀를 막는다. preview 없는 세션도 '(빈 세션)' 오표기 금지.
  const noRawIso = !/\dT\d{2}:\d{2}:\d{2}.*\+00:00/.test(pickerText)
  const noEmptyMislabel = !pickerText.includes('(빈 세션)')
  log('STEP3a: created_session_in_picker=' + createdInPicker + ' preview_label=' + previewLabelOk +
      ' no_raw_iso=' + noRawIso + ' no_empty_mislabel=' + noEmptyMislabel + ' sid=' + createdSid)
  // 생성된 세션 항목을 정확히 클릭(없으면 명확히 실패하도록 그대로 진행).
  if (createdSid && createdInPicker) {
    await page.getByText(createdSid, { exact: true }).last().click({ timeout: 8000 })
  }
  await page.waitForTimeout(1800)
  await page.screenshot({ path: `${OUT}-4-restored.png`, fullPage: true })
  const restored = await page.locator('body').innerText()
  const restoredOk = restored.includes(MARKER)
  log('STEP3: session_restored(마커 복원)=' + restoredOk)

  // (4) 이어 보내기 → 같은 세션에 누적.
  const followup = 'RESUME055-팔로업'
  const ta2 = page.locator('textarea').first()
  await ta2.fill(followup)
  await ta2.press('Enter')
  await page.waitForTimeout(4000)
  await page.screenshot({ path: `${OUT}-5-followup.png`, fullPage: true })
  const finalText = await page.locator('body').innerText()
  const followupOk = finalText.includes(followup) && finalText.includes(MARKER)
  log('STEP4: followup_in_same_session=' + followupOk)

  const ok = createdSid && resetOk && restoredOk && followupOk && previewLabelOk && noRawIso && noEmptyMislabel
  log(ok ? 'RESUME055_OK' : 'RESUME055_SUSPECT')
  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
