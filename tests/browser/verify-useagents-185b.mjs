/* 스펙 185 Phase B — useAgents 훅 추출 후 뮤테이션 왕복 회귀.
   로직 수술이라 tsc론 부족: 실제 생성→삭제 왕복으로 (a) 데이터 반영(list), (b) **커스텀 플로팅
   토스트 보존**(.ant-alert-success, antd message 아님 — deep-reasoner 최고위험), (c) notify 검증. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-loveqoo-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'
const NAME = `phaseb-${Date.now().toString(36)}`

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1360, height: 960 } })
const page = await ctx.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const log = (...a) => console.log(...a)
let fail = 0
const check = (ok, name) => { log(`${ok ? ' ok ' : 'FAIL'} ${name}`); if (!ok) fail++ }
// 커스텀 플로팅 토스트(성공)만 잡는다 — .ant-alert-success (antd message=.ant-message는 에러용).
const toastText = async () => {
  const a = page.locator('.ant-alert-success').last()
  return (await a.count()) ? (await a.textContent()) ?? '' : ''
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const rows0 = await page.locator('table tbody tr').count()

  // ── 생성 왕복(A.create) ──
  await page.getByRole('button', { name: '새 에이전트' }).click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill(NAME)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1500)
  const createToast = await toastText()
  check(/생성됨/.test(createToast), `B1 생성 토스트 = 커스텀 플로팅 Alert ("${createToast.slice(0, 30)}")`)
  // tr 카운트는 subRow(2줄 행, 스펙 146) 때문에 에이전트 수와 불일치 → "증가"만 판정, 정확 행은 B3.
  const rowsAfterCreate = await page.locator('table tbody tr').count()
  check(rowsAfterCreate > rows0, `B2 생성 후 list 증가 (${rows0}→${rowsAfterCreate})`)
  check(await page.locator('table tbody tr', { hasText: NAME }).count() > 0, `B3 새 행 '${NAME}' 존재`)
  await page.screenshot({ path: `${OUT}/185b-created.png` })
  await page.waitForTimeout(2600) // 토스트 자동소멸 대기(2.4s)

  // ── 삭제 왕복(A.remove) — 만든 것을 지워 정리 ──
  const row = page.locator('table tbody tr', { hasText: NAME }).first()
  // 행 안의 삭제(trash) 버튼 — 마지막 액션 아이콘. 없으면 드로어 경유.
  const delBtn = row.locator('button').last()
  await delBtn.click()
  await page.waitForTimeout(600)
  // 확인 모달(confirmDel) — "삭제" 확인 버튼
  const confirmBtn = page.getByRole('button', { name: /삭제|등록 해제|확인/ }).last()
  if (await confirmBtn.count()) { await confirmBtn.click(); await page.waitForTimeout(1400) }
  const delToast = await toastText()
  check(/삭제됨|등록 해제됨/.test(delToast), `B4 삭제 토스트 = 커스텀 플로팅 Alert ("${delToast.slice(0, 30)}")`)
  const rowsAfterDel = await page.locator('table tbody tr').count()
  check(rowsAfterDel === rows0, `B5 삭제 후 list 복원 (${rowsAfterCreate}→${rowsAfterDel})`)
  check(await page.locator('table tbody tr', { hasText: NAME }).count() === 0, `B6 '${NAME}' 행 제거됨`)

  check(pageErrors.length === 0, `Z1 pageerror 0 (실제: ${pageErrors.length})`)
  if (pageErrors.length) log('  pageerrors:', pageErrors.slice(0, 3))

  log(fail === 0 ? '\n✅ ALL PASS (USEAGENTS185B_OK)' : `\n❌ ${fail} FAILED`)
} catch (e) {
  log('EXCEPTION:', String(e)); fail++
} finally {
  await browser.close()
}
process.exit(fail === 0 ? 0 : 1)
