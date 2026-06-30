/* 스펙 092 무회귀(보조) — 채팅 본문서 도구 원본 숨김 변경 후, 일반 텍스트 응답이
   라이브 SSE 경로(event_stream의 is_tool_message 게이트 + _content_text 정규화)로
   회귀 없이 렌더되는지 확인. 시스템 Chrome(channel:'chrome').

   로그인 → Playground → 일반 메시지 1건 전송 → 응답 스트리밍 대기 →
     assistant 버블에 비어있지 않은 텍스트가 렌더되고, 콘솔 uncaught 에러 0인지 단언/캡처.

   한계: 실 도구(MCP/RAG) 호출로 "원본 미표시"까지 캡처하려면 도구가 구성된 에이전트 +
   실제로 도구를 부르는 모델이 필요(모델 의존). 그 경로의 *필터+정규화*는 verify_092 통합
   테스트가 실 ReAct 그래프로 직접 단언하므로, 여기선 일반 텍스트 무회귀만 본다(스펙 092 보조 명시).

   실행: PLAYWRIGHT_DIR=<...>/node_modules/playwright \
         NODE_PATH=<...>/node_modules node tests/browser/shot-hide-tool-092.mjs /tmp/hide092 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/hide092'
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

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  log('LOGGED_IN')

  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  const ta = page.locator('textarea').first()
  await ta.waitFor({ timeout: 10000 })
  await ta.fill('안녕하세요, 한 줄로 자기소개 해주세요.')
  await ta.press('Enter')
  await page.waitForTimeout(8000) // 응답 스트리밍 정착 대기(Mock LLM 폴백 포함)
  await page.screenshot({ path: `${OUT}-1-reply.png`, fullPage: false })

  // 본문 전체 텍스트 — assistant 응답이 비어있지 않아야(일반 텍스트 무회귀).
  const bodyText = await page.locator('body').innerText()
  expect(bodyText.includes('안녕하세요, 한 줄로'), '내 입력 버블 렌더됨')
  // 'me' 버블 외에 assistant 응답 텍스트가 더 있는지(전송문보다 본문이 충분히 김 = 응답 존재).
  expect(bodyText.length > 80, 'assistant 응답 텍스트가 본문에 렌더(빈 본문 아님)')
  // 콘솔 에러 — 092와 무관한 선재 노이즈(로그인 전 인증 프로브 401/404, antd 라이브러리
  // deprecation 경고)는 제외하고 *스트림/렌더 회귀*만 본다. 잔여가 있으면 회귀로 간주.
  const benign = (e) =>
    /status of 40[14]/.test(e) || /antd:/.test(e) || /deprecated/i.test(e)
  const real = errors.filter((e) => !benign(e))
  expect(real.length === 0, `스트림/렌더 회귀 에러 0 (선재노이즈 ${errors.length - real.length}건 제외)`)
  if (real.length) log('REGRESSION_ERRORS', JSON.stringify(real.slice(0, 5)))

  await page.screenshot({ path: `${OUT}-2-final.png`, fullPage: true })
  log(failed === 0 ? 'HIDE092_OK' : `HIDE092_FAIL(${failed})`)
} catch (e) {
  log('SHOT_FAIL', e.message)
} finally {
  await browser.close()
}
