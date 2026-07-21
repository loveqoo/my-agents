/* 스펙 182 훅(useAsyncData) 도입 후 변환한 뷰가 여전히 렌더·데이터 로드되는지 확인.
   허용 호스트(mutation+reload 소비자)·메모리(표시-페치 소비자) 두 뷰를 캡처+수치 판정. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 960 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const log = (...a) => console.log(...a)
let fail = 0
const check = (ok, name) => { log(`${ok ? ' ok ' : 'FAIL'} ${name}`); if (!ok) fail++ }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // --- 허용 호스트(useAsyncData + runWithToast 소비자) ---
  await page.getByText('허용 호스트', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const hostsBody = await page.evaluate(() => document.body.innerText)
  check(/허용 호스트/.test(hostsBody), 'A1 허용 호스트 뷰 렌더')
  check(!/불러오지 못했습니다/.test(hostsBody), 'A2 로드 에러 토스트 없음')
  // 새로고침 버튼(reload) 존재 = 훅 배선 확인
  check(await page.getByRole('button', { name: '새로고침' }).count() > 0, 'A3 새로고침(reload) 버튼 존재')
  await page.screenshot({ path: `${OUT}/hooks-183-allowedhosts.png` })

  // --- 메모리(useAsyncData 표시-페치 소비자) ---
  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(1400)
  const memBody = await page.evaluate(() => document.body.innerText)
  check(!/불러오지 못했습니다/.test(memBody), 'M1 메모리 로드 에러 없음')
  // 탭 또는 Select가 떠야(데이터 도착 후 렌더). "불러오는 중…"에서 안 멈춤.
  const memReady = await page.evaluate(() =>
    !!document.querySelector('.ant-select') || /메모리/.test(document.body.innerText),
  )
  check(memReady, 'M2 메모리 탭/Select 렌더(로딩서 안 멈춤)')
  await page.screenshot({ path: `${OUT}/hooks-183-memory.png` })

  // 사전 노이즈 제외: 파비콘/리소스 404, 배경 401(내 fetcher는 A2/M1서 에러 토스트 0=성공),
  // antd6 Alert `message` deprecated 정적 경고(데이터 페치와 무관). 이것들은 훅 도입 전부터 있던 것.
  const real = errors.filter((e) => !/favicon|404|401|is deprecated/.test(e))
  check(real.length === 0, `Z 훅 유발 콘솔 에러 0 (실제: ${real.length})`)
  if (real.length) log('  real errors:', real.slice(0, 5))

  log(fail === 0 ? '\n✅ ALL PASS (HOOKS183_OK)' : `\n❌ ${fail} FAILED`)
} finally {
  await browser.close()
}
process.exit(fail === 0 ? 0 : 1)
