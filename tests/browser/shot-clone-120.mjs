/* 스펙 120 검증 — 에이전트 복제 버튼(저마찰 재사용). 시스템 Chrome.
   admin(vite :5173) 로그인 → API로 원본 시드 → 상세 드로어 "복제" 버튼 클릭 → "(복사본)" 생성 확인.
   백엔드 복제 로직은 verify_120이 이미 검증 — 여기선 버튼 렌더+배선(클릭→복사본)만 결정적으로 확인
   (스펙 114 교훈: 브라우저가 놓친 렌더/배선 지점을 잡는다).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-clone-120.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/clone-120.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1100 } })
const page = await ctx.newPage()

const SRC = `clone-ui-${Math.random().toString(36).slice(2, 8)}`
const cleanupIds = []

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 원본 시드(세션 쿠키로 프록시 /api 사용) — 테스트 독립성 확보.
  const seed = await page.request.post(`${URL}/api/agents`, {
    data: { name: SRC, config: { model: 'mock-llm', prompt: '', capabilities: [], impl: 'orchestrate' } },
  })
  check(seed.ok(), `S 원본 시드 생성 (status ${seed.status()})`)
  const srcAgent = await seed.json()
  cleanupIds.push(srcAgent.id)

  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)

  // 원본 행 클릭 → 상세 드로어.
  const srcRow = page.locator('tr', { hasText: SRC }).first()
  check(await srcRow.count() > 0, 'H1 원본 행이 목록에 보임')
  await srcRow.click()
  await page.waitForTimeout(700)

  // "복제" 버튼 렌더 확인(관리 권한 무관 — 항상 노출).
  const cloneBtn = page.getByRole('button', { name: '복제' })
  check(await cloneBtn.count() > 0, 'H2 상세 드로어에 "복제" 버튼 렌더')
  await page.screenshot({ path: OUT, fullPage: true })
  console.log('SHOT', OUT)

  // 클릭 → 복사본 생성(배선). 목록에 "(복사본)" 등장.
  await cloneBtn.first().click()
  await page.waitForTimeout(1200)
  const body = await page.locator('body').innerText()
  check(body.includes('(복사본)'), 'H3 클릭 후 "(복사본)" 에이전트 등장(복제 배선 동작)')
  await page.screenshot({ path: OUT.replace('.png', '-after.png'), fullPage: true })
  console.log('SHOT', OUT.replace('.png', '-after.png'))

  // 복사본 id 회수(정리용).
  const listResp = await page.request.get(`${URL}/api/agents`)
  const arr = await listResp.json()
  for (const a of arr) if (a.name === `${SRC} (복사본)`) cleanupIds.push(a.id)
} catch (e) {
  check(false, 'EXC ' + (e?.message ?? e))
} finally {
  // 시드/복사본 정리.
  for (const id of cleanupIds) {
    try { await page.request.delete(`${URL}/api/agents/${id}`) } catch { /* best effort */ }
  }
  await browser.close()
}

console.log(fails.length ? `\n❌ ${fails.length} FAILED` : '\n✅ ALL PASS (SHOT120_OK)')
process.exit(fails.length ? 1 : 0)
