/* 스펙 089 — 커스텀 에이전트 준수 3상태 배지 검증(시스템 Chrome).
   admin(vite :5173) 로그인 후:
   (1) 미해결 impl(does_not_exist_089) 에이전트를 API로 생성(저장 허용=합의 B, 쿠키 인증).
   (2) 에이전트 목록 — '준수' 컬럼에 그 행이 빨강 '설정 실패' 배지, 일반 ui 행은 초록 '준수'.
   (3) 디테일 드로어 — 헤더 '설정 실패' 태그 + 빨강 Alert('런타임이 서빙을 거부').
   (4) 정리 — 생성 에이전트 삭제(자체 격리).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-conformance-089.mjs /tmp/conf-089 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/conf-089'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)
let badId = null

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // (1) 미해결 impl 에이전트 생성 — 쿠키 인증으로 same-origin POST(저장 허용=합의 B).
  const created = await page.evaluate(async () => {
    const r = await fetch('/api/agents', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: 'CONF089 설정실패 데모',
        config: { model: 'mock-llm', persona: '', historyDepth: 10, impl: 'does_not_exist_089' },
      }),
    })
    return { status: r.status, body: await r.json() }
  })
  log('CREATE status=' + created.status + ' conformance=' + created.body?.conformance)
  badId = created.body?.id

  // (2) 에이전트 목록 재진입 → '준수' 컬럼 캡처. 생성은 API 직접이라 SPA 캐시 밖 →
  //     전체 리로드로 listAgents 재요청을 강제(클릭만으론 재요청 안 함).
  await page.reload({ waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}-1-list.png`, fullPage: true })

  const listText = await page.locator('body').innerText().catch(() => '')
  const hasConfHeader = /준수/.test(listText)
  const hasConfigError = /설정 실패/.test(listText)
  log('LIST: 준수컬럼=' + hasConfHeader + ' 설정실패배지=' + hasConfigError)

  // (3) 그 에이전트 행 클릭 → 디테일 드로어.
  await page.getByText('CONF089 설정실패 데모', { exact: false }).first().click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}-2-detail.png`, fullPage: false })

  const detailText = await page.locator('body').innerText().catch(() => '')
  const hasAlert = /런타임이 서빙을 거부/.test(detailText)
  const noServing = !/서빙 중/.test(detailText) || hasAlert // config_error면 '서빙 중' 초록 배지 대신 '설정 실패'
  log('DETAIL: 거부Alert=' + hasAlert + ' 서빙배지숨김=' + noServing)

  const ok = created.body?.conformance === 'config_error' && hasConfHeader && hasConfigError && hasAlert
  log(ok ? 'CONF089_OK' : 'CONF089_SUSPECT')
  log('CONSOLE_ERRORS=' + JSON.stringify(errors.slice(0, 8)))
} catch (e) {
  log('SHOT_FAIL', e.message)
  await page.screenshot({ path: `${OUT}-fail.png`, fullPage: true }).catch(() => {})
} finally {
  // (4) 정리 — 생성 에이전트 삭제.
  if (badId) {
    await page.evaluate(async (id) => {
      await fetch(`/api/agents/${id}`, { method: 'DELETE', credentials: 'include' }).catch(() => {})
    }, badId).catch(() => {})
  }
  await browser.close()
}
