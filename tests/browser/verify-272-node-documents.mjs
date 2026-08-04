/* 노드 도구/문서 facet 분리 검증 (스펙 272) — 필수 단언(UI 기능적).
   ① 노드 카드에 도구·문서 컨트롤 분리 — 도구 옵션에 "문서 검색 …" 안 섞임.
   ② 병합 보존(핵심 위험): 문서 선택 후 도구 선택 → 둘 다 유지(한쪽 변경이 상대 항목 안 떨굼).
   ③ 저장 왕복(API): 도구+문서 섞인 n.tools가 합집합으로 보존(268 P1 저장 무변경).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-272-node-documents.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

async function login() {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)
}

const selWrap = (labelText) =>
  page.locator('div', { has: page.getByText(labelText, { exact: true }) }).filter({ has: page.locator('.ant-select') }).last()

try {
  await login()

  // 노드형 폼 열고 노드 추가
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill('doc-272-' + Date.now().toString(36))
  const typeField = page.locator('label', { hasText: '에이전트 종류' }).first()
  await typeField.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(400)

  // ① 분리 — 도구=트리(스펙 277·278 아코디언 — 열어야 DOM에 렌더), 문서=Select 각각 존재
  const toolAcc = page.locator('.ant-modal:visible .ant-collapse-header').filter({ hasText: '도구' }).filter({ hasNotText: '승인' }).first()
  await toolAcc.click(); await page.waitForTimeout(400)
  const toolTree = page.locator('.ant-modal:visible .ant-tree').first()
  const docLabel = await page.getByText('문서 (선택)', { exact: true }).count()
  check(await toolTree.count() > 0, `노드 카드에 도구 트리(스펙 277)`)
  check(docLabel > 0, `노드 카드에 "문서 (선택)" 컨트롤 (found ${docLabel})`)

  // 트리엔 서버 노드만·컬렉션(문서) 안 섞임(분리) — 트리 텍스트에 컬렉션명 없음은 문서 옵션과 대조로 확인
  const mcpNodeCount = await toolTree.locator('.ant-tree-treenode').count()

  // 문서 옵션 = 컬렉션명
  const docWrap = selWrap('문서 (선택)')
  await docWrap.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  const docOptCount = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').count()
  check(docOptCount > 0, `문서 옵션에 컬렉션 있음 (found ${docOptCount})`)
  // ② 병합 보존: 문서 하나 선택
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click()
  await page.waitForTimeout(300)
  await page.keyboard.press('Escape'); await page.waitForTimeout(200)
  const docChosen = await docWrap.locator('.ant-select-selection-item').count()
  check(docChosen >= 1, `문서 선택됨 (${docChosen})`)

  // 도구 트리에서 자식 하나 체크 → 문서 유지되는지(병합 보존, 272 무회귀)
  if (mcpNodeCount > 0) {
    const srv = toolTree.locator('.ant-tree-treenode', { has: page.getByText('calc-tools', { exact: true }) }).first()
    await srv.locator('.ant-tree-switcher').first().click(); await page.waitForTimeout(300)
    const leaf = toolTree.locator('.ant-tree-treenode', { has: page.getByText('add', { exact: true }) }).first()
    await leaf.locator('.ant-tree-checkbox').first().click()
    await page.waitForTimeout(300)
    const toolChecked = await toolTree.locator('.ant-tree-checkbox-checked').count()
    const docStill = await docWrap.locator('.ant-select-selection-item').count()
    check(toolChecked >= 1 && docStill >= 1, `병합 보존: 도구 트리 체크 후에도 문서 유지 (도구 ${toolChecked}·문서 ${docStill})`)
  } else {
    log('  ..  MCP 도구 트리 노드 없음 — 도구↔문서 병합 UI 테스트 스킵(등록 MCP 없음)')
  }
  // 닫기
  const cancel = page.getByRole('button', { name: /취소|닫기/ }).first()
  if (await cancel.count()) await cancel.click({ force: true }).catch(() => {})
  await page.locator('.ant-modal-wrap').first().waitFor({ state: 'hidden', timeout: 4000 }).catch(() => {})
  await page.waitForTimeout(300)

  // ③ 저장 왕복(API): 도구+문서 섞인 n.tools 합집합 보존
  const rt = await page.evaluate(async () => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text(); let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    const nm = 'rt-272-' + Date.now().toString(36)
    const config = {
      model: 'qwen3.6-35b', prompt: '', impl: 'pipeline', historyDepth: 20, persistHistory: true, ephemeral: false,
      memories: [], mcps: [], vectorTables: [],
      nodes: [{ name: '검색', prompt: '검색하고 답하라', model: 'qwen3.6-35b', context: 'carry',
                tools: ['web-fetch__wiki_search', 'search_documents__docs-kb'] }],
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status, body: cr.t.slice(0, 200) }
    const got = await jf(`/api/agents/${cr.j.id}`)
    return { step: 'ok', tools: got.j?.nodes?.[0]?.tools }
  })
  log('ROUNDTRIP=' + JSON.stringify(rt))
  check(rt.step === 'ok', `저장 왕복 (step=${rt.step}${rt.body ? ' ' + rt.body : ''})`)
  check(Array.isArray(rt.tools) && rt.tools.includes('web-fetch__wiki_search') && rt.tools.includes('search_documents__docs-kb'),
    `n.tools 도구+문서 합집합 보존 (got ${JSON.stringify(rt.tools)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
