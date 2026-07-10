/* 비영속 승인 고정 검증 (스펙 282) — 필수 단언(UI 기능적).
   ① 비영속+도구 선택: 승인 행 Select='승인 없음'·disabled(문구의 약속을 UI가 이행).
   ② 영속 복귀: Select 활성·'기본값 사용' 복원(폼 상태 불변).
   ③ 비영속 저장 왕복: toolPolicy[capId].approval.required === false.
   ④ 폰트 정합: 승인 행에 <code> 없음.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-282-approval-pinning.mjs */
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
const nm = 'ap282-' + Date.now().toString(36)
const cleanup = { agents: [] }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const modal = page.locator('.ant-modal:visible').last()
  await page.getByPlaceholder('예: research-assistant').fill(nm)
  const mw = modal.locator('div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await mw.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: 'mock-llm' }).first().click()
  await page.waitForTimeout(200)
  await modal.getByText('비영속', { exact: false }).first().click(); await page.waitForTimeout(300)
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

  // ── ① 비영속: 헤더='승인 없음' 고정(거짓 어포던스 '선택' 제거) + Select 고정 ──
  const apprHeader = await modal.locator('.ant-collapse-header').filter({ hasText: '도구 승인 오버라이드' }).first().innerText()
  check(apprHeader.includes("'승인 없음' 고정") && !apprHeader.includes('선택'), `① 헤더: '승인 없음' 고정(선택 아님) (got ${JSON.stringify(apprHeader)})`)
  // 상설 안내(편집 어포던스 서술)는 비영속에 부재 — 고정 안내가 관리자 게이트까지 대체(282 후속2)
  const panelTxt = await modal.locator('.ant-collapse-panel').filter({ has: page.locator('.ant-select') }).last().innerText()
  check(!panelTxt.includes('덮어씁니다'), `① 비영속: 상설 안내('덮어씁니다') 부재`)
  check(panelTxt.includes('이 저장은 관리자만 할 수 있습니다'), `① 비영속: 고정 안내에 관리자 게이트 포함`)
  const apprRow = modal.locator('.ant-collapse-panel .ant-select').filter({ hasText: '승인 없음' }).first()
  check(await apprRow.count() > 0, `① 승인 행 Select='승인 없음' 고정`)
  const disabled = await apprRow.evaluate((el) => el.className.includes('ant-select-disabled'))
  check(disabled, `① Select disabled(잠금)`)
  // ④ 폰트: 승인 행에 <code> 없음
  const codeCount = await modal.locator('.ant-collapse-panel code').count()
  check(codeCount === 0, `④ 승인 행 <code> 소멸(평문 폰트) (found ${codeCount})`)

  // ── ② 영속 복귀: 활성·'기본값 사용' 복원 ──
  await page.getByRole('button', { name: '이전', exact: true }).click(); await page.waitForTimeout(400)
  await modal.getByText('영속 (기본)', { exact: true }).click(); await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await modal.locator('.ant-collapse-header').filter({ hasText: '도구 승인 오버라이드' }).first().click()
  await page.waitForTimeout(400)
  const apprHeader2 = await modal.locator('.ant-collapse-header').filter({ hasText: '도구 승인 오버라이드' }).first().innerText()
  check(apprHeader2.includes('선택'), `② 영속 복귀: 헤더 '선택' 복원 (got ${JSON.stringify(apprHeader2)})`)
  const panelTxt2 = await modal.locator('.ant-collapse-panel').filter({ has: page.locator('.ant-select') }).last().innerText()
  check(panelTxt2.includes('덮어씁니다'), `② 영속 복귀: 상설 안내 복원`)
  const apprRow2 = modal.locator('.ant-collapse-panel .ant-select').filter({ hasText: '기본값 사용' }).first()
  check(await apprRow2.count() > 0, `② 영속 복귀: '기본값 사용' 복원`)
  const disabled2 = await apprRow2.evaluate((el) => el.className.includes('ant-select-disabled'))
  check(!disabled2, `② 영속 복귀: Select 활성`)

  // ── ③ 다시 비영속 → 저장 → toolPolicy required:false ──
  await page.getByRole('button', { name: '이전', exact: true }).click(); await page.waitForTimeout(400)
  await modal.getByText('비영속', { exact: false }).first().click(); await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1200)
  const saved = await page.evaluate(async (n) => {
    const r = await fetch('/api/agents', { credentials: 'include' })
    const list = await r.json()
    const a = (Array.isArray(list) ? list : list.items ?? []).find((x) => x.name === n)
    return a ? { id: a.id, eph: a.ephemeral, tp: a.toolPolicy } : null
  }, nm)
  if (saved?.id) cleanup.agents.push(saved.id)
  log('SAVED=' + JSON.stringify(saved))
  check(!!saved && saved.eph === true, `③ 저장: ephemeral=true`)
  check(saved?.tp?.['mcp:local-tools/delete_record']?.approval?.required === false,
    `③ 저장: toolPolicy '승인 없음' 기록 (got ${JSON.stringify(saved?.tp)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
