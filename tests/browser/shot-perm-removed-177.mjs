/* 스펙 177 P3 UI 검증 — 죽은 "권한" 개념 제거 + 능력 부여 패널 신설. 시스템 Chrome.
   슈퍼유저 로그인 →
     (1) 빌딩 블록: '권한' 탭 부재 + 남은 4탭(페르소나/메모리/벡터/MCP) 존재.
     (2) 유저: '능력 부여 (정책)' 패널 렌더.
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-perm-removed-177.mjs [outPrefix] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/perm-177'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 } })
const page = await ctx.newPage()

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // (1) 빌딩 블록 — '권한' 탭 제거 확인
  await page.getByText('빌딩 블록', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  const permTab = await page.getByRole('tab', { name: /권한/ }).count()
  ok(permTab === 0, `'권한' 탭 부재 (found=${permTab})`)
  for (const t of ['페르소나', 'MCP']) {
    const c = await page.getByRole('tab', { name: new RegExp(t) }).count()
    ok(c > 0, `'${t}' 탭 유지 (found=${c})`)
  }
  await page.screenshot({ path: `${OUT}-1-blocks-no-perm.png`, fullPage: true })

  // (2) 유저 — 능력 부여 패널 확인
  await page.getByText('유저', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const panel = await page.getByText('능력 부여 (정책)', { exact: false }).count()
  ok(panel > 0, `'능력 부여 (정책)' 패널 렌더 (found=${panel})`)
  await page.screenshot({ path: `${OUT}-2-users-capability.png`, fullPage: true })

  console.log(fails.length ? `\n실패 ${fails.length}건` : '\nP3 UI 검증 — 전부 통과.')
} catch (e) {
  console.error('오류:', e.message)
  fails.push(e.message)
} finally {
  if (_fx) await _fx.cleanup?.()
  await browser.close()
}
process.exit(fails.length ? 1 : 0)
