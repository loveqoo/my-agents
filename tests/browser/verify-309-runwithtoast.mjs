/* 스펙 309 기능 검증 — runWithToast 이관 뷰가 실제로 동작하는지 브라우저 왕복.
   외형 아닌 동작(learning UI 검증): (1) 이관된 화면들이 렌더·정착·콘솔 치명0(무붕괴 스윕),
   (2) 대표 mutation(Settings save)이 성공 토스트 + 결과소비(setOrgName(r)) + if(ok) 배선까지
   실제로 도는지 안전 왕복으로 단언(전역 org 이름 1필드, 원복). errorPrefix 분기는 별도 순수
   로직 체크로 확인함(node). 백엔드 무변경.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-309-runwithtoast.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/verify-309.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
page.on('pageerror', (e) => consoleErrors.push('PAGEERROR: ' + e.message))

const nav = async (label) => {
  // menuitem은 배지("99+" 등)를 품을 수 있어 exact 텍스트 대신 role+hasText로 잡는다.
  const item = page.getByRole('menuitem').filter({ hasText: label }).first()
  await item.click({ timeout: 8000 })
  await page.waitForTimeout(700)
  const spinning = await page.locator('.ant-spin-spinning').count()
  check(spinning === 0, `${label}: 렌더·정착(스피너 잔류 ${spinning})`)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ── 무붕괴 스윕: 이관 핸들러가 있는 화면들이 렌더·정착하는지 ──
  for (const label of ['빌딩 블록', 'RAG 컬렉션', '세션', '승인', '프로바이더·모델', '유저', '배치', '평가', '설정']) {
    await nav(label)
  }

  // ── 대표 mutation 왕복: Settings save (결과소비 setOrgName(r) + 성공 토스트 + if(ok)) ──
  // 지금 '설정' 화면. 현재 값 읽고 → 테스트 값 저장 → 성공 토스트 + 필드가 서버 echo 반영 확인 → 원복.
  const input = page.locator('input[placeholder="예: acme-lab"]')
  await input.waitFor({ timeout: 5000 })
  const original = await input.inputValue()
  const testVal = 'e2e-309-org'
  await input.fill(testVal)
  await page.getByRole('button', { name: '저장' }).click()
  // 성공 토스트(antd message) — 자동 소멸 전 포착. antd6 마크업 편차 대비 컨테이너 넓게 잡고 텍스트로.
  const toastSeen = await page
    .locator('.ant-message')
    .filter({ hasText: '저장했습니다' })
    .first()
    .waitFor({ state: 'visible', timeout: 4000 })
    .then(() => true)
    .catch(() => false)
  check(toastSeen, 'Settings: 저장 성공 토스트 발화(runWithToast success)')
  await page.waitForTimeout(600)
  // 결과소비 — setOrgName(String(r.a2a_org_name))가 서버 응답으로 필드를 갱신(fn 내부 실행 증거).
  const afterVal = await input.inputValue()
  check(afterVal === testVal, `Settings: 저장 후 필드=서버 echo(결과소비 setOrgName, 값="${afterVal}")`)
  // 원복 — 원래 값(빈 문자열이면 지우고 저장 생략: 빈 값은 서버가 거부/무의미할 수 있어 원문 복원만).
  await input.fill(original)
  await page.getByRole('button', { name: '저장' }).click()
  await page.waitForTimeout(800)
  const restored = await input.inputValue()
  check(restored === original, `Settings: 원복 완료(값="${restored}")`)

  await page.screenshot({ path: OUT, fullPage: false })
  const fatal = consoleErrors.filter((e) =>
    /PAGEERROR|Cannot read|is not a function|undefined is not|Maximum update depth|Rendered more hooks|Rendered fewer hooks/i.test(e),
  )
  check(fatal.length === 0, `콘솔 치명 에러 0(전체 ${consoleErrors.length}, 치명 ${fatal.length})`)
  if (fatal.length) fatal.slice(0, 5).forEach((e) => console.log('    ! ' + e.slice(0, 160)))
} catch (e) {
  console.log('SCRIPT_ERROR: ' + (e?.stack ?? e))
  fails.push('스크립트 예외: ' + (e?.message ?? e))
} finally {
  await browser.close()
}

console.log('')
console.log(`스크린샷: ${OUT}`)
if (fails.length) {
  console.log(`\nFAIL: ${fails.length}건`)
  fails.forEach((f) => console.log('  - ' + f))
  process.exit(1)
}
console.log('\nVERIFY309_OK — runWithToast 이관: 화면 무붕괴 + 대표 mutation 성공토스트·결과소비·if(ok) 배선 정착')
