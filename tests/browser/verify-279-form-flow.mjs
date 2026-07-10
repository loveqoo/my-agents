/* 에이전트 폼 흐름 3종 검증 (스펙 279) — 필수 단언(UI 기능적).
   ① step① 순서: 식별 이름→설명→에이전트 종류→모델→페르소나(커서 탐색).
   ② 비영속: 장기=기선택 제거·새 선택 잠금(placeholder), 단기=활성 유지+안내 hint(사용자 재확인 설계).
   ③ step② 직접형: 도구·문서 단일 Collapse(헤더에 둘 다), 승인 오버라이드는 초기 부재→도구 체크 시
      도구와 문서 사이 출현. 저장 왕복: tools+vectorTables+toolPolicy 반영.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-279-form-flow.mjs */
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

  const uiName = 'ff279-' + rand
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const modal = page.locator('.ant-modal:visible').last()

  // ── ① step① 순서(커서 탐색 — 앞 매치 뒤부터) ──
  const t1 = await modal.innerText()
  const order1 = ['식별 이름', '설명', '에이전트 종류', '모델', '페르소나']
  let cur = 0
  const idx1 = order1.map((l) => { const at = t1.indexOf(l, cur); if (at >= 0) cur = at + l.length; return at })
  check(idx1.every((v) => v >= 0), `① step① 순서 ${order1.join('→')} (idx=${JSON.stringify(idx1)})`)

  await page.getByPlaceholder('예: research-assistant').fill(uiName)
  // 종류가 모델보다 앞이라(279 ①) 바깥 div 매칭이 종류 Select를 집음 — 최내곽(last)으로 스코프.
  const modelWrap = modal.locator('div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await modelWrap.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: 'mock-llm' }).first().click()
  await page.waitForTimeout(200)

  // ── ② 비영속: 저장 방식=비영속 → step②서 장기 잠금·단기 활성 ──
  await modal.getByText('비영속 (1회성)', { exact: false }).first().click().catch(async () => {
    // Segmented 라벨이 다르면 '비영속' 부분 일치로
    await modal.getByText('비영속', { exact: false }).first().click()
  })
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  const t2 = await modal.innerText()
  check(t2.includes('비영속(1회성)') || t2.includes('비영속'), `② step②에 비영속 상태 반영`)
  // 장기: 비영속 placeholder(공용 컨트롤 문구)
  check(t2.includes('비영속(1회성)은 기억을 쓰지 않습니다') || t2.includes('비영속(1회성) 에이전트는 기억을'),
    `② 장기 기억 비영속 잠금 문구 노출`)
  // 단기: 활성 유지 + 비영속 안내 hint
  check(t2.includes('비영속에서도 요청에 담긴 대화에 적용'), `② 단기 기억 활성 유지+안내 hint`)
  const shortSel = modal.locator('div', { has: page.getByText('단기 기억', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last().locator('.ant-select').first()
  const shortDisabled = await shortSel.evaluate((el) => el.className.includes('ant-select-disabled'))
  check(!shortDisabled, `② 단기 Select 활성(disabled 아님)`)
  // 영속 복귀(스펙 282 갱신) — 비영속은 승인 Select가 '승인 없음'으로 고정되므로, ③의 승인 값
  // 설정은 영속 상태에서 수행한다(비영속 고정 자체는 verify-282가 단언).
  await page.getByRole('button', { name: '이전', exact: true }).click(); await page.waitForTimeout(400)
  await modal.getByText('영속 (기본)', { exact: true }).click(); await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(500)

  // ── ③ Collapse 하나에 아이템(도구/승인/문서) — 승인은 도구 선택 시 사이에 출현 ──
  // step② 도구/문서 아이템은 한 Collapse의 형제 헤더(사용자 지시: Collapse(Item,Item,...)).
  const stepHeaders = () => modal.locator('.ant-collapse-header').allInnerTexts()
  const h0 = (await stepHeaders()).map((h) => h.replace(/\n/g, ' '))
  const hasTools0 = h0.some((h) => /^도구\s/.test(h))
  const hasDocs0 = h0.some((h) => /^문서\s/.test(h))
  const hasAppr0 = h0.some((h) => h.includes('도구 승인 오버라이드'))
  check(hasTools0 && hasDocs0, `③ 도구/문서 형제 아이템 헤더 (got ${JSON.stringify(h0)})`)
  check(!hasAppr0, `③ 초기: 승인 아이템 부재(도구 미선택)`)
  // 도구 아이템 열고 local-tools 확장 → delete_record 체크
  const toolsHeader = modal.locator('.ant-collapse-header').filter({ hasText: '도구' }).filter({ hasNotText: '승인' }).filter({ hasNotText: '문서' }).first()
  await toolsHeader.click()
  await page.waitForTimeout(400)
  const tree = modal.locator('.ant-tree').first()
  const srv = tree.locator('.ant-tree-treenode', { has: page.getByText('local-tools', { exact: true }) }).first()
  await srv.locator('.ant-tree-switcher').first().click(); await page.waitForTimeout(300)
  const leaf = tree.locator('.ant-tree-treenode', { has: page.getByText('delete_record', { exact: true }) }).first()
  await leaf.locator('.ant-tree-checkbox').first().click(); await page.waitForTimeout(400)
  // 승인 아이템이 도구와 문서 사이에 출현
  const h1 = (await stepHeaders()).map((h) => h.replace(/\n/g, ' '))
  const iTool = h1.findIndex((h) => /^도구\s/.test(h))
  const iAppr = h1.findIndex((h) => h.includes('도구 승인 오버라이드'))
  const iDoc = h1.findIndex((h) => /^문서\s/.test(h))
  check(iAppr >= 0, `③ 도구 체크 → 승인 아이템 출현 (headers=${JSON.stringify(h1)})`)
  check(iTool >= 0 && iTool < iAppr && iAppr < iDoc, `③ 헤더 순서: 도구 → 승인 → 문서 (${iTool},${iAppr},${iDoc})`)
  // 승인 아이템 열어 값 설정(관리자)
  await modal.locator('.ant-collapse-header').filter({ hasText: '도구 승인 오버라이드' }).first().click()
  await page.waitForTimeout(400)
  // antd v6: 패널 content 클래스=.ant-collapse-panel(.ant-collapse-content 아님 — 249 v6 DOM 교훈)
  const apprSel = modal.locator('.ant-select', { hasText: '기본값 사용' }).first()
  await apprSel.click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '승인 필요 · 관리자' }).first().click()
  await page.waitForTimeout(300)
  // 문서 아이템 열어 컬렉션 체크
  await modal.locator('.ant-collapse-header').filter({ hasText: '문서' }).filter({ hasNotText: '승인' }).first().click()
  await page.waitForTimeout(400)
  const docBox = modal.locator('.ant-collapse-panel .ant-checkbox-wrapper').first()
  const docName = (await docBox.innerText()).split('\n')[0].trim()
  await docBox.click(); await page.waitForTimeout(300)

  // 저장 왕복
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1200)
  const saved = await page.evaluate(async (nm) => {
    const r = await fetch('/api/agents', { credentials: 'include' })
    const list = await r.json()
    const a = (Array.isArray(list) ? list : list.items ?? []).find((x) => x.name === nm)
    return a ? { id: a.id, tools: a.tools, vt: a.vectorTables, tp: a.toolPolicy, mem: a.memories, eph: a.ephemeral } : null
  }, uiName)
  if (saved?.id) cleanup.agents.push(saved.id)
  log('SAVED=' + JSON.stringify(saved))
  check(!!saved && saved.eph === false, `저장: ephemeral=false(영속 복귀 후 저장 — 282 갱신)`)
  check(!!saved && (saved.mem ?? []).length === 0, `② 저장: memories 비어 있음 (got ${JSON.stringify(saved?.mem)})`)
  check(!!saved && JSON.stringify(saved.tools) === JSON.stringify(['local-tools__delete_record']), `③ 저장: tools (got ${JSON.stringify(saved?.tools)})`)
  check(!!saved && (saved.vt ?? []).includes(docName), `③ 저장: vectorTables에 '${docName}' (got ${JSON.stringify(saved?.vt)})`)
  check(!!saved && saved.tp?.['mcp:local-tools/delete_record']?.approval?.required === true,
    `③ 저장: toolPolicy 관리자 승인 (got ${JSON.stringify(saved?.tp)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
