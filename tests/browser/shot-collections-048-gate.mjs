/* RAG 게이트 배너 양성 케이스 검증 (스펙 048, 적대 리뷰 #3) — 시스템 Chrome.
   임베딩 모델을 파괴적으로 지우지 않고, /models?kind=embedding 응답을 빈 배열로 *가로채*
   "임베딩 모델 0개" 상태를 브라우저 세션에만 만든다(DB 무손상). 단언:
   (1) 경고 Alert 배너가 보이는지, (2) '컬렉션 생성' 버튼이 disabled인지.
   route 가로채기는 load() 호출 전(라우트 등록 후 진입)이라 loaded 가드 통과 후에도 빈 모델 반영.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=verify032@example.com ADMIN_PASSWORD='Verify032!pw' \
         node tests/browser/shot-collections-048-gate.mjs /tmp/coll048gate.png */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/coll048gate.png'
// self-fixture(스펙 050 Phase 3): ADMIN_EMAIL 미지정이면 던짐용 super 즉석 시드 → 종료 시 자동 삭제.
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

// 임베딩 모델 목록만 빈 배열로 가로챈다(chat 목록·그 외 /models는 통과).
await page.route('**/models?kind=embedding', (r) => r.fulfill({
  status: 200, contentType: 'application/json', body: '[]',
}))

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: OUT, fullPage: true })

  const banner = await page.getByText('임베딩 모델이 없어 RAG 기능을 사용할 수 없습니다').count()
  const createBtn = page.getByRole('button', { name: /컬렉션 생성/ }).first()
  const disabled = await createBtn.isDisabled().catch(() => null)
  log('GATE banner=' + (banner > 0) + ' createDisabled=' + disabled)
  log(banner > 0 && disabled === true ? 'PASS 게이트 양성 케이스' : 'FAIL 게이트 미작동')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: OUT }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
