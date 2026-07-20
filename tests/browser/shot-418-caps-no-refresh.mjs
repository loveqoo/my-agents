/* 스펙 418 — 능력 설정 토글이 전체 새로고침을 안 부르는지 검증(시스템 Chrome).
   프로바이더·모델 → 등록 모델의 "능력·설정" 팝오버 열기 → 능력 Switch 토글 →
   ① 팝오버 유지 ② 토글 후 네트워크는 PUT /models/{id}만, 프로바이더·available GET 재조회 0
   ③ 재열람 시 저장값 반영.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         VW=1280 node tests/browser/shot-418-caps-no-refresh.mjs /tmp/shot-418 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/shot-418'
const VW = Number(process.env.VW ?? 1280)
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let fails = 0
const check = (cond, msg) => { log((cond ? 'ok  ' : 'FAIL ') + msg); if (!cond) fails++ }

// 네트워크 카운터(경로별)
const net = { putModel: 0, getProviders: 0, getAvail: 0 }
page.on('request', (req) => {
  const u = req.url(); const m = req.method()
  if (m === 'PUT' && /\/models\//.test(u)) net.putModel++
  if (m === 'GET' && /\/providers(\?|$)/.test(u)) net.getProviders++
  if (m === 'GET' && /available[-_]?models|\/models(\?|$)/.test(u)) net.getAvail++
})

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 프로바이더·모델 진입
  await page.getByText('프로바이더·모델', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  // 능력·설정 버튼이 보이는 프로바이더를 찾는다(등록 모델 있는 것). 없으면 프로바이더를 눌러본다.
  let capBtn = page.getByRole('button', { name: '능력·설정' }).first()
  if (!(await capBtn.count())) {
    // 프로바이더 목록에서 하나씩 클릭해 등록 모델 노출
    const provRows = page.locator('.ant-list-item, [role="row"], .ant-card')
    const n = Math.min(await provRows.count(), 6)
    for (let i = 0; i < n; i++) {
      await provRows.nth(i).click().catch(() => {})
      await page.waitForTimeout(700)
      if (await page.getByRole('button', { name: '능력·설정' }).count()) break
    }
    capBtn = page.getByRole('button', { name: '능력·설정' }).first()
  }
  await page.screenshot({ path: `${OUT}-list.png`, fullPage: true })
  check(await capBtn.count() > 0, '등록 모델의 "능력·설정" 버튼 존재')
  if (!(await capBtn.count())) throw new Error('능력·설정 버튼을 못 찾음(등록 모델 없음?)')

  // 팝오버 열기
  await capBtn.click()
  await page.getByText('모델 능력·설정', { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(400)
  // 팝오버 내부 능력 Switch(첫 번째) 상태 기록 → 토글
  const popSwitch = page.locator('.ant-popover-container .ant-switch').first()
  const before = await popSwitch.getAttribute('aria-checked')
  // 카운터 리셋(토글 이후만 계측)
  net.putModel = 0; net.getProviders = 0; net.getAvail = 0
  await popSwitch.click()
  await page.waitForTimeout(1500) // PUT + (버그면) reload 대기
  const popStillOpen = await page.getByText('모델 능력·설정', { exact: true }).count()
  const after = await popSwitch.getAttribute('aria-checked')
  await page.screenshot({ path: `${OUT}-after-toggle.png`, fullPage: true })
  log(`NET after toggle=${JSON.stringify(net)} switch ${before}->${after} popoverOpen=${popStillOpen}`)

  check(net.putModel === 1, `토글 → PUT /models 1회 (got ${net.putModel})`)
  check(net.getProviders === 0, `토글 → 프로바이더 GET 재조회 0 (got ${net.getProviders})`)
  check(net.getAvail === 0, `토글 → 모델/available GET 재조회 0 (got ${net.getAvail})`)
  check(popStillOpen > 0, '토글 후 팝오버 유지(새로고침 없음)')
  check(before !== after, `능력 값 실제 반영 (${before}->${after})`)

  // 재열람: 팝오버 닫고 다시 열어 저장값 유지 확인(제자리 갱신)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  await capBtn.click()
  await page.getByText('모델 능력·설정', { exact: true }).waitFor({ timeout: 5000 })
  const reopened = await page.locator('.ant-popover-container .ant-switch').first().getAttribute('aria-checked')
  check(reopened === after, `재열람 시 저장값 유지 (${reopened} == ${after})`)

  // 원복(테스트 부수효과 최소화 — 같은 능력 다시 토글해 원상)
  await page.locator('.ant-popover-container .ant-switch').first().click()
  await page.waitForTimeout(1000)

  log(fails === 0 ? 'SHOT418_OK' : `SHOT418_FAIL(${fails})`)
  process.exitCode = fails === 0 ? 0 : 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
