/* 대화 저장 토글 이동 검증 (스펙 280) — 필수 단언(UI 기능적).
   ① step①: 저장 방식 바로 아래 대화 저장(순서), 관계 설명 문구.
   ② step③ 세부: '대화 저장'·'저장·영속' 부재.
   ③ 기능: 토글 off → 저장 persistHistory=false. 비영속 전환 → 토글 disabled(279 ② 유지).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-280-persist-toggle.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1200 } })).newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const rand = Date.now().toString(36)
const cleanup = { agents: [] }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  const nm = 'pt280-' + rand
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const modal = page.locator('.ant-modal:visible').last()
  await page.getByPlaceholder('예: research-assistant').fill(nm)

  // ── ① 순서 + 설명 문구 (스펙 281: '대화 저장' Field → '저장 항목' 리스트로 갱신) ──
  const t1 = await modal.innerText()
  const iMode = t1.indexOf('저장 방식')
  const iPersist = t1.indexOf('저장 항목', iMode)
  check(iMode >= 0 && iPersist > iMode, `① 저장 방식 바로 아래 저장 항목 (idx=${iMode},${iPersist})`)
  check(t1.includes('세션 재개·인스펙터 소급 열람 가능'), `① 관계 설명(ON) 노출`)
  // 토글 off → 설명 전환
  const sw = modal.locator('div', { has: page.getByText('저장 항목', { exact: true }) })
    .filter({ has: page.locator('.ant-switch') }).last().locator('.ant-switch').first()
  await sw.click(); await page.waitForTimeout(300)
  const t1b = await modal.innerText()
  check(t1b.includes('세션·기억·통계는 유지'), `① 관계 설명(OFF): 세션·기억·통계 유지 문구`)

  // 비영속 전환 → 리스트 소멸(281 — disabled 대신 부재)
  await modal.getByText('비영속', { exact: false }).first().click()
  await page.waitForTimeout(300)
  check(!(await modal.innerText()).includes('대화 내용'), `③ 비영속 → 저장 항목 리스트 소멸`)
  // 영속 복귀(OFF 값 유지 확인) 후 다음 단계로
  await modal.getByText('영속 (기본)', { exact: true }).click()
  await page.waitForTimeout(300)

  // ── ② step③ 세부에 부재 ──
  const mw = modal.locator('div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await mw.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: 'mock-llm' }).first().click()
  await page.waitForTimeout(200)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  const t3 = await modal.innerText()
  check(!t3.includes('저장·영속') && !t3.includes('대화 저장') && !t3.includes('저장 항목'), `② step③ 세부에 저장 관련 구획 부재`)

  // ── ③ 저장 왕복: persistHistory=false ──
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1200)
  const saved = await page.evaluate(async (n) => {
    const r = await fetch('/api/agents', { credentials: 'include' })
    const list = await r.json()
    const a = (Array.isArray(list) ? list : list.items ?? []).find((x) => x.name === n)
    return a ? { id: a.id, ph: a.persistHistory, eph: a.ephemeral } : null
  }, nm)
  if (saved?.id) cleanup.agents.push(saved.id)
  log('SAVED=' + JSON.stringify(saved))
  check(!!saved && saved.ph === false && saved.eph === false, `③ 저장: persistHistory=false·ephemeral=false (got ${JSON.stringify(saved)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
