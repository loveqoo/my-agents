/* 에이전트 목록 재설계 검증 (스펙 284) — 필수 단언(UI 기능적).
   ① 출처 탭 3개·기본 Internal(UI)·전환 시 소스별 목록. 소유/소스 Select 부재.
   ② 내 것 행 tint(배경 스타일)·가시성/소유 태그 부재. ③ UI 탭 '종류' Tag, Code 탭엔 부재.
   ④ 프롬프트 컬럼 부재. ⑤ 탭별 검색 placeholder + 종류 검색(283 무회귀). ⑥ 상태=색 점+툴팁.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-284-agents-list.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1100 } })).newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const rand = Date.now().toString(36)
const MINE = 'al284-mine-' + rand
const cleanup = { agents: [] }

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 내 것 픽스처(노드형 — 종류 태그도 함께 확인)
  const made = await page.evaluate(async (nm) => {
    const r = await fetch('/api/agents', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nm, config: { model: 'mock-llm', prompt: '', impl: 'pipeline', nodes: [{ name: 'n', prompt: 'p', model: 'mock-llm', tools: [] }] } }) })
    return r.ok ? (await r.json()).id : null
  }, MINE)
  if (made) cleanup.agents.push(made)
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForTimeout(800)

  // ── ① 탭 3개 + 기본 UI ──
  for (const t of ['내부 (UI)', '내부 (Code)', '외부']) {
    check((await page.getByRole('tab', { name: t }).count()) > 0, `① 탭 '${t}' 존재`)
  }
  const uiSelected = await page.getByRole('tab', { name: '내부 (UI)' }).getAttribute('aria-selected')
  check(uiSelected === 'true', `① 기본 탭=Internal (UI)`)
  const pageText = await page.locator('main, body').first().innerText()
  check(!pageText.includes('소유: 전체') && !pageText.includes('소스: 전체'), `① 소유/소스 Select 부재`)

  // ── ④⑤ 프롬프트 컬럼 부재 + placeholder ──
  const headTxt = await page.locator('.dt-antd thead').first().innerText().catch(() => '')
  check(!headTxt.includes('프롬프트'), `④ 프롬프트 컬럼 부재 (head=${JSON.stringify(headTxt.replace(/\n/g, ' '))})`)
  check(headTxt.includes('종류'), `③ UI 탭에 '종류' 컬럼`)
  check((await page.getByPlaceholder('이름 검색').count()) > 0, `⑤ 이름 검색 placeholder`)
  check((await page.locator('.ant-select', { hasText: '종류: 전체' }).count()) > 0, `⑤ UI 탭 종류 Select`)
  check((await page.getByText('A2A 공개만', { exact: true }).count()) > 0, `⑤ UI 탭 A2A 체크박스`)

  // ── ⑤ 종류 검색(283 무회귀) + ③ 종류 Tag ──
  await page.getByPlaceholder('이름 검색').fill(MINE)
  await page.waitForTimeout(500)
  const row = page.locator('.dt-antd tbody tr', { has: page.getByText(MINE, { exact: false }) }).first()
  check((await row.count()) > 0, `픽스처 행 노출`)
  check((await row.getByText('노드형', { exact: true }).count()) > 0, `③ 종류 Tag '노드형'`)

  // ── ② 내 것 tint ──
  const tintClass = await row.evaluate((el) => el.className)
  check(tintClass.includes('dt-row-tint-blue'), `② 내 것(private) 행 blue tint (class=${tintClass})`)
  const rowTxt = await row.innerText()
  check(!/private|public|내 것|공유/.test(rowTxt), `② 가시성/소유 태그 부재 (row=${JSON.stringify(rowTxt.slice(0, 80))})`)

  // ── ⑥ 상태 점 + 툴팁(유휴=노랑 — 방금 생성, 활성화 전) ──
  const dot = row.locator('span[aria-label]').filter({ hasText: '' }).last()
  const dotLabel = await row.locator('span[aria-label="유휴"]').count()
  check(dotLabel > 0, `⑥ 상태 점(aria-label=유휴) 존재`)

  // ── ① 탭 전환: Code 탭 — 종류 컬럼 없음·placeholder 변경 ──
  await page.getByRole('tab', { name: '내부 (Code)' }).click()
  await page.waitForTimeout(500)
  const headTxt2 = await page.locator('.dt-antd thead').first().innerText().catch(() => '')
  check(!headTxt2.includes('종류'), `③ Code 탭엔 '종류' 컬럼 없음`)
  check((await page.locator('.ant-select', { hasText: 'A2A: 전체' }).count()) > 0, `⑤ Code 탭 A2A Select`)
  check((await page.getByText('A2A 공개만', { exact: true }).count()) === 0, `⑤ Code 탭엔 A2A 체크박스 없음`)
  // External: 이름만 + 상태 컬럼/필터 부재(사용자: 외부는 상태 관리 안 함)
  await page.getByRole('tab', { name: '외부' }).click()
  await page.waitForTimeout(500)
  check((await page.getByPlaceholder('이름 검색').count()) > 0, `⑤ External 이름 검색만`)
  check((await page.locator('.ant-select', { hasText: '상태: 전체' }).count()) === 0, `⑤ External 상태 필터 부재`)
  const headTxt3 = await page.locator('.dt-antd thead').first().innerText().catch(() => '')
  check(!headTxt3.includes('상태'), `⑥ External 상태 컬럼 부재`)
  await page.getByRole('tab', { name: '내부 (Code)' }).click()
  await page.waitForTimeout(400)
  // UI 픽스처는 Code 탭에 안 보임
  check((await page.getByText(MINE, { exact: false }).count()) === 0, `① 탭 분리: UI 에이전트가 Code 탭에 없음`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
