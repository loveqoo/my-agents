/* 도구 선택 트리(ToolTree) 검증 (스펙 277) — 필수 단언(UI 기능적).
   ① 직접형 폼: 서버 부모 + 도구 자식 노드 존재(계층). ② 자식 하나 체크→저장 config.tools 1개·
   mcps 파생. ③ 부모 체크→그 서버 도구 전체가 value에(저장 tools=서버 도구 수). ④ 노드 카드에도
   트리·문서 병합 보존. ⑤ 오버라이드에도 트리.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-277-tool-tree.mjs */
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

async function closeModal() {
  const cancel = page.getByRole('button', { name: /^취소$/ }).first()
  if (await cancel.count()) await cancel.click({ force: true }).catch(() => {})
  await page.keyboard.press('Escape').catch(() => {})
  await page.locator('.ant-modal-wrap').first().waitFor({ state: 'hidden', timeout: 4000 }).catch(() => {})
  await page.waitForTimeout(300)
}
// antd Tree 노드: 라벨 텍스트로 해당 treenode의 체크박스를 찾아 클릭
const checkNode = async (scope, title) => {
  const node = scope.locator('.ant-tree-treenode', { has: page.getByText(title, { exact: true }) }).first()
  await node.locator('.ant-tree-checkbox').first().click()
  await page.waitForTimeout(300)
}
// 스펙 278: 트리가 아코디언 안+1 depth 초기화 — 열고 서버 스위처를 펼친 뒤 리프 상호작용.
const openToolAccordion = async (scope) => {
  const header = scope.locator('.ant-collapse-header').filter({ hasText: '도구' }).filter({ hasNotText: '승인' }).first()
  await header.click(); await page.waitForTimeout(400)
}
const expandServer = async (tree, server) => {
  const node = tree.locator('.ant-tree-treenode', { has: page.getByText(server, { exact: true }) }).first()
  await node.locator('.ant-tree-switcher').first().click(); await page.waitForTimeout(300)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ── ①② 직접형 폼: 트리 계층 + 자식 하나 체크 → 저장 ──
  const uiName = 'tt277-' + rand
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill(uiName)
  const modelWrap = page.locator('.ant-modal div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last() // 279: 종류가 모델보다 앞 — 최내곽으로
  await modelWrap.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: 'mock-llm' }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(600)
  const modal = page.locator('.ant-modal:visible').last()
  await openToolAccordion(modal)
  const tree = modal.locator('.ant-tree').first()
  await expandServer(tree, 'calc-tools')
  const parentNode = await tree.locator('.ant-tree-treenode', { has: page.getByText('calc-tools', { exact: true }) }).count()
  const childNode = await tree.locator('.ant-tree-treenode', { has: page.getByText('add', { exact: true }) }).count()
  check(parentNode > 0, `① 서버 부모 노드 'calc-tools' (found ${parentNode})`)
  check(childNode > 0, `① 도구 자식 노드 'add' (found ${childNode})`)
  // 자식 'echo'(calc-tools) 하나 체크 — 첫 서버의 echo. targeting/local과 이름 겹치므로 calc-tools 스코프.
  const calcNode = tree.locator('.ant-tree-treenode', { has: page.getByText('add', { exact: true }) }).first()
  // add를 고른다(고유)
  await calcNode.locator('.ant-tree-checkbox').first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1200)
  const saved = await page.evaluate(async (nm) => {
    const r = await fetch('/api/agents', { credentials: 'include' })
    const list = await r.json()
    const a = (Array.isArray(list) ? list : list.items ?? []).find((x) => x.name === nm)
    return a ? { id: a.id, tools: a.tools, mcps: a.mcps } : null
  }, uiName)
  if (saved?.id) cleanup.agents.push(saved.id)
  log('SAVED=' + JSON.stringify(saved))
  check(!!saved && JSON.stringify(saved.tools) === JSON.stringify(['calc-tools__add']), `② 자식 체크→config.tools=['calc-tools__add'] (got ${JSON.stringify(saved?.tools)})`)
  check(!!saved && JSON.stringify(saved.mcps) === JSON.stringify(['calc-tools']), `② mcps=['calc-tools'] 파생 (got ${JSON.stringify(saved?.mcps)})`)
  await closeModal()

  // ── ③ 부모 체크 = 서버 도구 전체 ──
  const uiName2 = 'tt277-parent-' + rand
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill(uiName2)
  const mw2 = page.locator('.ant-modal div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last() // 279: 종류가 모델보다 앞 — 최내곽으로
  await mw2.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: 'mock-llm' }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(600)
  await openToolAccordion(page.locator('.ant-modal:visible').last())
  const tree2 = page.locator('.ant-modal:visible .ant-tree').first()
  // web-fetch 부모 체크(wiki_search+wiki_page 2개) — 부모는 1 depth라 확장 불필요(스펙 278)
  await checkNode(tree2, 'web-fetch')
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1200)
  const saved2 = await page.evaluate(async (nm) => {
    const r = await fetch('/api/agents', { credentials: 'include' })
    const list = await r.json()
    const a = (Array.isArray(list) ? list : list.items ?? []).find((x) => x.name === nm)
    return a ? { id: a.id, tools: (a.tools || []).sort(), mcps: a.mcps } : null
  }, uiName2)
  if (saved2?.id) cleanup.agents.push(saved2.id)
  log('SAVED2=' + JSON.stringify(saved2))
  check(!!saved2 && JSON.stringify(saved2.tools) === JSON.stringify(['web-fetch__wiki_page', 'web-fetch__wiki_search']),
    `③ 부모 체크→서버 도구 전체 (got ${JSON.stringify(saved2?.tools)})`)
  await closeModal()

  // ── ④ 노드 카드에도 트리 + 문서 병합 보존 ──
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill('tt277-node-' + rand)
  const typeField = page.locator('label', { hasText: '에이전트 종류' }).first()
  await typeField.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click(); await page.waitForTimeout(500)
  const nodeModal = page.locator('.ant-modal:visible').last()
  await openToolAccordion(nodeModal)
  const nodeTree = nodeModal.locator('.ant-tree').first()
  check(await nodeTree.count() > 0, `④ 노드 카드에 도구 트리 존재`)
  // 문서 선택(있으면) → 도구 트리 체크 → 문서 유지
  const docWrap = nodeModal.locator('div', { has: page.getByText('문서 (선택)', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await docWrap.locator('.ant-select').first().click(); await page.waitForTimeout(300)
  const docOpts = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').count()
  if (docOpts > 0) {
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click()
    await page.waitForTimeout(200)
    await page.keyboard.press('Escape'); await page.waitForTimeout(200)
    await expandServer(nodeTree, 'calc-tools')
    await checkNode(nodeTree, 'add')
    const docStill = await docWrap.locator('.ant-select-selection-item').count()
    check(docStill >= 1, `④ 병합 보존: 도구 트리 체크 후 문서 유지 (${docStill})`)
  } else {
    log('  ..  컬렉션 없음 — ④ 병합 스킵')
  }
  await closeModal()

  // ── ⑤ 오버라이드에도 트리 ──
  const pr = await page.evaluate(async (nm) => {
    const r = await fetch('/api/agents', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: nm, config: { model: 'mock-llm', persona: 't', mcps: [], tools: [] } }) })
    return r.ok ? (await r.json()).id : null
  }, 'tt277-ov-' + rand)
  if (pr) cleanup.agents.push(pr)
  await page.getByRole('menuitem', { name: 'Playground' }).click(); await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click(); await page.waitForTimeout(400)
  await page.getByText('tt277-ov-' + rand, { exact: false }).first().click(); await page.waitForTimeout(600)
  await page.locator('button[title*="오버라이드"]').first().click(); await page.waitForTimeout(500)
  const drawer = page.getByRole('dialog')
  await drawer.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(500)
  await openToolAccordion(drawer)
  check(await drawer.locator('.ant-tree').count() > 0, `⑤ 오버라이드에 도구 트리 존재`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}
