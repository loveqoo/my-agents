/* 에이전트 생성 모달 레이아웃 검증 (스펙 075) — 시스템 Chrome.
   admin(vite :5173) 로그인 → '새 에이전트' 클릭 → 생성 모달 캡처.
   메모리 타입 라벨의 boundingRect.height로 글자단위 세로래핑을 검출한다
   (정상=한 줄 ≈ 20px대, 깨짐=글자수만큼 세로로 늘어나 60px+).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         VW=1280 node tests/browser/shot-agent-create.mjs /tmp/agent-create */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/agent-create'
const VW = Number(process.env.VW ?? 1280)
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 960 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  // 모바일은 사이더 접힘 — 에이전트 뷰가 기본이라 바로 '새 에이전트' 가능
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}-full.png`, fullPage: true })

  // 메모리 타입 라벨 높이 측정: '단기(세션)'·'장기 기억 (mem0)' 행의 이름 span.
  // antd 6 모달 본문 클래스는 .ant-modal-container (구 .ant-modal-content 아님).
  const heights = await page.evaluate(() => {
    const labels = [...document.querySelectorAll('.ant-modal-container .ant-checkbox-wrapper')]
    return labels.slice(0, 6).map((el) => {
      // 새 구조: wrapper > span(label) > span(flex col) > [이름(span/code), 설명].
      // 이름만 재려면 flex-col(라벨 span의 첫 요소 자식)의 첫 요소 자식을 잡는다.
      const labelSpan = el.querySelector('.ant-checkbox + span')
      const col = labelSpan?.firstElementChild
      const name = col?.firstElementChild ?? col
      const r = (name ?? el).getBoundingClientRect()
      return { text: (name?.textContent ?? '').slice(0, 16), h: Math.round(r.height), w: Math.round(r.width) }
    })
  })
  log('LABEL_HEIGHTS=' + JSON.stringify(heights))
  // 한 줄이면 h ≲ 28. 글자단위 세로래핑이면 h가 글자수배로 큼.
  const broken = heights.filter((x) => x.h > 40)
  log('VERTICAL_WRAP_BROKEN=' + JSON.stringify(broken))

  // 토글 무회귀: 첫 메모리 체크박스 토글 후 checked 반영
  const firstBox = page.locator('.ant-modal-container .ant-checkbox-input').first()
  const before = await firstBox.isChecked()
  await page.locator('.ant-modal-container .ant-checkbox-wrapper').first().click()
  await page.waitForTimeout(150)
  const after = await firstBox.isChecked()
  log('TOGGLE before=' + before + ' after=' + after + ' changed=' + (before !== after))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
