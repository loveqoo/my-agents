/* 스펙 091 검증 — 터미널 콘솔식 입력 히스토리 재호출(↑/↓). 시스템 Chrome(channel:'chrome').
   로그인 → Playground → 입력 3개 전송 → 입력창 비움 →
     caret 맨앞 ↑ = 직전 입력, 다시 ↑ = 더 과거, 최古 초과 ↑ = clamp,
     ↓ = 더 최근, 끝까지 ↓ = 초안(빈문자) 복원,
     **caret이 맨앞 아닐 때 ↑는 재호출 안 함**(음성 단언) — 을 단언/캡처한다.
   전부 통과면 마지막에 `HIST091_OK`를 찍는다.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-input-history-091.mjs /tmp/hist091 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/hist091'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)

let failed = 0
function expect(cond, label) {
  if (cond) log('  ✓ ' + label)
  else {
    failed++
    log('  ✗ ' + label)
  }
}

const MSGS = ['첫 입력 메시지', '두 번째 입력 메시지', '세 번째 입력 메시지'] // 전송 순서(old→new)

try {
  // 로그인
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  log('LOGGED_IN')

  // Playground 진입.
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  const ta = page.locator('textarea').first()
  await ta.waitFor({ timeout: 10000 })

  // 입력 3개 전송. 'me' 버블은 전송 즉시 쌓이므로 히스토리에 들어간다. 다음 전송 전 스트리밍이
  // 가라앉길 기다린다(전송 중엔 Sender가 loading이라 입력이 막힐 수 있어 키 시퀀스가 흔들림 방지).
  for (const m of MSGS) {
    await ta.fill(m)
    await ta.press('Enter')
    await page.waitForTimeout(5000) // 응답 스트리밍 정착 대기
  }
  await page.screenshot({ path: `${OUT}-1-after-sends.png` })

  // 입력창은 전송 후 비어 있어야(onSubmit setDraft('')) — caret은 자연히 0.
  await ta.click()
  await ta.fill('') // 확실히 비움(onChange로 탐색 리셋)
  await page.waitForTimeout(200)
  expect((await ta.inputValue()) === '', '전송 후 입력창 비어 있음')

  // --- ↑ 재호출: 직전 → 더 과거 → 최古 clamp ---
  await ta.press('ArrowUp')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === MSGS[2], '첫 ↑ = 직전 입력(세 번째)')

  await ta.press('ArrowUp')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === MSGS[1], '둘째 ↑ = 두 번째 입력')

  await ta.press('ArrowUp')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === MSGS[0], '셋째 ↑ = 첫 입력(최古)')

  await ta.press('ArrowUp')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === MSGS[0], '최古 초과 ↑ = clamp(첫 입력 유지)')
  await page.screenshot({ path: `${OUT}-2-recall-oldest.png` })

  // --- ↓ 더 최근 → 끝까지 내려오면 빈 초안 복원 ---
  await ta.press('ArrowDown')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === MSGS[1], '↓ = 두 번째(더 최근)')

  await ta.press('ArrowDown')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === MSGS[2], '↓ = 세 번째(최신)')

  await ta.press('ArrowDown')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === '', '최신서 ↓ = 빈 초안 복원·탐색 종료')

  // --- 음성 단언: caret이 맨앞 아니면 ↑는 재호출 안 함 ---
  await ta.fill('abc') // onChange로 탐색 리셋, caret은 끝(3)
  await page.waitForTimeout(120)
  await ta.press('ArrowUp')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === 'abc', 'caret 맨앞 아닐 때 ↑는 재호출 안 함(값 유지)')
  await page.screenshot({ path: `${OUT}-3-no-recall-midcaret.png` })

  // --- caret을 맨앞으로 옮긴 뒤엔 ↑ 재호출 됨(진입조건 양성 확인) ---
  await ta.press('Home') // caret → 줄 맨앞(단일행이라 절대 0)
  await page.waitForTimeout(80)
  await ta.press('ArrowUp')
  await page.waitForTimeout(120)
  expect((await ta.inputValue()) === MSGS[2], 'caret 맨앞으로 옮긴 뒤 ↑ = 재호출 재개')

  // --- P2 회귀: 재호출 값이 현재 입력과 같아도 caret이 끝으로 가야 함(no-op setDraft 경계) ---
  // 입력창에 최신 입력을 그대로 채우고 caret을 맨앞으로 → ↑ 재호출은 같은 값을 돌려주지만(setDraft no-op)
  // caret은 끝으로 이동해야 한다(recallSeq 단조 카운터가 effect를 발화).
  // 빈값→최신: 직전 단계의 navigating 상태를 확실히 리셋(동일 값 fill은 onChange 미발화).
  await ta.fill('')
  await page.waitForTimeout(80)
  await ta.fill(MSGS[2]) // onChange로 탐색 리셋, draft=최신입력(비탐색)
  await page.waitForTimeout(120)
  await ta.press('Home') // caret → 0
  await page.waitForTimeout(80)
  await ta.press('ArrowUp')
  await page.waitForTimeout(150)
  const caretPos = await ta.evaluate((el) => el.selectionStart)
  expect((await ta.inputValue()) === MSGS[2], '값 동일 재호출: 값 유지(최신)')
  expect(caretPos === MSGS[2].length, '값 동일 재호출: caret이 끝으로 이동(no-op setDraft여도)')

  if (failed === 0) log('HIST091_OK')
  else log(`HIST091_FAIL ${failed} assertion(s) failed`)
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
  else log('NO_CONSOLE_ERRORS')
} catch (e) {
  log('HIST091_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-FAIL.png` }).catch(() => {})
  if (errors.length) log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} finally {
  await browser.close()
}
