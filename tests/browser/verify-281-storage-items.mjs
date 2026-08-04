/* 저장 항목 리스트 검증 (스펙 281) — 필수 단언(UI 기능적).
   ① 영속: '저장 항목' 리스트에 '대화 내용' 행(토글+설명). off → 설명 전환.
   ② 비영속: 리스트 소멸 → "저장 항목 없음"+승인 제약 문구. 영속 복귀 시 리스트 복원.
   ③ step② 승인 아이템(도구 선택 후): 비영속이면 제약 문구 노출.
   ④ 저장 왕복: persistHistory=false.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-281-storage-items.mjs */
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
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  const nm = 'si281-' + rand
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const modal = page.locator('.ant-modal:visible').last()
  await page.getByPlaceholder('예: research-assistant').fill(nm)

  // ── ① 영속: 저장 항목 리스트 + 대화 내용 행 ──
  const t1 = await modal.innerText()
  const iMode = t1.indexOf('저장 방식')
  const iItems = t1.indexOf('저장 항목', iMode)
  check(iMode >= 0 && iItems > iMode, `① 저장 방식 아래 '저장 항목' (idx=${iMode},${iItems})`)
  check(t1.includes('대화 내용') && t1.includes('세션 재개·인스펙터 소급 열람 가능'), `① '대화 내용' 행+설명(ON)`)
  // 토글 off → 설명 전환
  const itemsField = modal.locator('div', { has: page.getByText('저장 항목', { exact: true }) })
    .filter({ has: page.locator('.ant-switch') }).last()
  await itemsField.locator('.ant-switch').first().click(); await page.waitForTimeout(300)
  check((await modal.innerText()).includes('세션·기억·통계는 유지'), `① OFF 설명: 세션·기억·통계 유지`)

  // ── ② 비영속: 리스트 소멸 + 요약 + 승인 제약 ──
  await modal.getByText('비영속', { exact: false }).first().click(); await page.waitForTimeout(300)
  const t2 = await modal.innerText()
  check(t2.includes('저장 항목 없음 — 아무것도 기록하지 않습니다'), `② 비영속: 요약 문구`)
  check(t2.includes("승인이 필요하지 않은 도구만 실행할 수 있습니다"), `② 비영속: 승인 제약 문구(긍정형)`)
  check(!t2.includes('대화 내용'), `② 비영속: '대화 내용' 행 소멸`)
  // 영속 복귀 → 리스트 복원(OFF 값 유지)
  await modal.getByText('영속 (기본)', { exact: true }).click(); await page.waitForTimeout(300)
  const t3 = await modal.innerText()
  check(t3.includes('대화 내용') && t3.includes('세션·기억·통계는 유지'), `② 영속 복귀: 리스트 복원+OFF 값 유지`)

  // ── ③ step② 승인 아이템의 비영속 제약 문구 ──
  await modal.getByText('비영속', { exact: false }).first().click(); await page.waitForTimeout(300)
  const mw = modal.locator('div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await mw.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: 'mock-llm' }).first().click()
  await page.waitForTimeout(200)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(500)
  // 도구 선택 → 승인 아이템 열기
  const toolsHeader = modal.locator('.ant-collapse-header').filter({ hasText: '도구' }).filter({ hasNotText: '승인' }).filter({ hasNotText: '문서' }).first()
  await toolsHeader.click(); await page.waitForTimeout(400)
  const tree = modal.locator('.ant-tree').first()
  const srv = tree.locator('.ant-tree-treenode', { has: page.getByText('local-tools', { exact: true }) }).first()
  await srv.locator('.ant-tree-switcher').first().click(); await page.waitForTimeout(300)
  const leaf = tree.locator('.ant-tree-treenode', { has: page.getByText('delete_record', { exact: true }) }).first()
  await leaf.locator('.ant-tree-checkbox').first().click(); await page.waitForTimeout(400)
  await modal.locator('.ant-collapse-header').filter({ hasText: '도구 승인 오버라이드' }).first().click()
  await page.waitForTimeout(400)
  const t4 = await modal.innerText()
  check(t4.includes("'승인 없음' 상태의 도구만 실행할 수 있어"), `③ 승인 아이템에 비영속 고정 안내(282 후속2 문구)`)

  // ── ④ 저장 왕복: 영속+대화 내용 off (①에서 끈 값이 유지되는지) ──
  // 위에서 비영속으로 저장하면 persistHistory 검증이 안 되므로 이전으로 돌아가 영속으로 저장
  await page.getByRole('button', { name: '이전', exact: true }).click(); await page.waitForTimeout(400)
  await modal.getByText('영속 (기본)', { exact: true }).click(); await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
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
  check(!!saved && saved.ph === false && saved.eph === false, `④ 저장: persistHistory=false·ephemeral=false (got ${JSON.stringify(saved)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
