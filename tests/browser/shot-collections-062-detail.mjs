/* 스펙 062 브라우저 E2E (가장 충실) — Admin에서 *중복 이름* 컬렉션 생성 시
   토스트가 "→ 409"가 아니라 서버 `detail`("같은 이름의 컬렉션이 이미 있습니다")을 보이는지 실증.
   D1(프런트 detail 추출)이 실제 UI 토스트까지 닿는지 — 단위/통합이 못 보는 마지막 글루를 잡는다.

   기존 컬렉션 이름 하나를 그대로 입력해 중복을 유도하므로 DB를 더럽히지 않는다(생성 실패 = 무변경).

   실행: PLAYWRIGHT_DIR=<abs>/node_modules/playwright \
         node tests/browser/shot-collections-062-detail.mjs /tmp/coll062.png */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/coll062.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1000)

  // 기존 컬렉션 이름 하나를 행 텍스트에서 채취(중복 유도용). 시드 docs_kb 등.
  const existingName = await page.evaluate(() => {
    // DataTable은 평범한 <table>. 이름은 td 안 <span style="font-weight:500">{name}</span>.
    // td.textContent는 설명까지 합쳐지므로 span 단위로 본다.
    const spans = Array.from(document.querySelectorAll('td span'))
    for (const s of spans) {
      const t = (s.textContent || '').trim()
      // 컬렉션 이름: 영문 소문자 시작 + 언더스코어(예: docs_kb). 숫자(차원)·Tag 텍스트 배제.
      if (/^[a-z][a-z0-9_]{2,}$/.test(t)) return t
    }
    return null
  })
  log('기존 컬렉션 이름(중복 유도):', existingName)
  if (!existingName) throw new Error('기존 컬렉션 이름을 찾지 못함 — 시드 필요')

  await page.getByRole('button', { name: /컬렉션 생성/ }).first().click()
  await page.locator('.ant-modal-title', { hasText: '컬렉션 생성' }).waitFor({ timeout: 5000 })

  await page.getByPlaceholder('예: 사내 위키').fill(existingName)
  // 임베딩 모델 Select 열고 첫 옵션 선택
  await page.locator('.ant-modal .ant-select').first().click()
  await page.waitForTimeout(400)
  await page.locator('.ant-select-item-option').first().click()
  await page.waitForTimeout(200)

  // 모달의 '생성' 버튼
  await page.locator('.ant-modal-footer').getByRole('button', { name: '생성' }).click()

  // 토스트(message.error) 대기 후 텍스트 채취
  await page.locator('.ant-message-notice').first().waitFor({ timeout: 6000 })
  await page.waitForTimeout(300)
  const toast = (await page.locator('.ant-message-notice').first().textContent())?.trim() ?? ''
  log('TOAST:', JSON.stringify(toast))
  await page.screenshot({ path: OUT, fullPage: true })

  const showsDetail = toast.includes('이미') && toast.includes('컬렉션')
  const showsRawStatus = /→\s*409/.test(toast)
  log('showsServerDetail=' + showsDetail + ' showsRawStatus=' + showsRawStatus)
  log(showsDetail && !showsRawStatus
    ? 'PASS 서버 detail 가시화(→ 409 아님)'
    : 'FAIL detail 미노출 또는 상태코드만 노출')
  if (!(showsDetail && !showsRawStatus)) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: OUT }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
