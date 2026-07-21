/* 스펙 191 e2e — RAG 인스펙터 가독성 + 에이전트별 유사도 임계값(필터).
   U) 어드민 폼: 문서(docs-kb) 배선 → "최소 유사도" 슬라이더 노출 → 0.5 설정 → 저장.
   P) API 왕복: ragMinScore=0.5 보존.
   R1) 플레이그라운드(min=0.5): "문서 검색" → mock 저점수 전부 드롭 → 0건 + 검색어 노출(필터 작동).
   R2) API로 min=0 에이전트 → 검색 → 인스펙터 히트 카드(파일명·유사도 배지) + 척도 범례 + 검색어.

   mock-llm이 search_documents tool_call을 결정적으로 낸다(mock_remote _TOOL_TRIGGERS, 스펙 191).
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-rag-threshold-191.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-{{GITHUB_ORG}}-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'
const NAME = `ragthr-${Date.now().toString(36)}`

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1000 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

const waitFor = async (pattern, timeout = 25000) => {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    if (pattern.test(await page.locator('body').innerText())) return true
    await page.waitForTimeout(600)
  }
  return false
}
const selectAgent = async (name) => {
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(name, { exact: false }).first().click()
  await page.waitForTimeout(500)
}
const openInspector = async () => {
  // 마지막 메시지의 "인스펙터" 링크를 눌러 trace 패널을 연다.
  await page.getByText('인스펙터', { exact: false }).last().click()
  await page.waitForTimeout(700)
}

let idA = null
let idB = null
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // ── U) 폼: 문서 배선 → 슬라이더 → 0.5 저장 ──
  await page.getByRole('button', { name: '새 에이전트' }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill(NAME)
  // 슬라이더는 RAG 배선 전엔 없어야 한다.
  const sliderBefore = await page.getByText('문서 검색 — 최소 유사도', { exact: false }).count()
  ok(sliderBefore === 0, 'U1 문서 미배선 시 슬라이더 숨김')
  // "문서" 패널 열고 docs-kb 체크.
  const docsPanel = page.locator('.ant-modal-container .ant-collapse-header', { hasText: '문서' }).first()
  await docsPanel.click()
  await page.waitForTimeout(400)
  await page.locator('.ant-modal-container .ant-checkbox-wrapper', { hasText: 'docs-kb' }).first().click()
  await page.waitForTimeout(400)
  let sliderShown = true
  await page.getByText('문서 검색 — 최소 유사도', { exact: false }).first().waitFor({ timeout: 5000 }).catch(() => { sliderShown = false })
  ok(sliderShown, 'U2 문서 배선 → 최소 유사도 슬라이더 노출')
  // 슬라이더 핸들 포커스 후 ArrowRight×10 (step 0.05) → 0.5.
  const handle = page.locator('.ant-modal-container .ant-slider-handle').first()
  await handle.click()
  for (let i = 0; i < 10; i++) { await page.keyboard.press('ArrowRight'); await page.waitForTimeout(30) }
  await page.waitForTimeout(200)
  const valShown = await waitFor(/0\.50/, 3000)
  ok(valShown, 'U3 슬라이더 0.50 설정')
  await page.screenshot({ path: `${OUT}/rag-thr-191-form.png` })
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  let saved = true
  await page.locator('.ant-modal-wrap').first().waitFor({ state: 'hidden', timeout: 12000 }).catch(() => { saved = false })
  ok(saved, 'U4 저장 후 모달 닫힘')
  await page.waitForTimeout(1000)

  // ── P) API 왕복: ragMinScore=0.5 ──
  const agents = await (await fetch(`${API}/agents`, { headers: { Cookie: cookie } })).json()
  const a = (Array.isArray(agents) ? agents : []).find((x) => x.name === NAME)
  ok(!!a, `P1 에이전트 생성됨 (${NAME})`)
  idA = a?.id
  ok(Math.abs((a?.ragMinScores?.['docs-kb'] ?? 0) - 0.5) < 1e-6,
    `P2 ragMinScores["docs-kb"] 왕복 보존 (got ${JSON.stringify(a?.ragMinScores)})`)

  // ── R1) min=0.5 실행 → 필터로 0건 + 검색어 ──
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await selectAgent(NAME)
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('docs-kb 문서 검색해줘'); await ta.press('Enter')
  ok(await waitFor(/인스펙터/, 25000), 'R1a 응답 도착(인스펙터 링크)')
  await openInspector()
  const insText1 = await page.locator('body').innerText()
  ok(/문서 검색/.test(insText1) && /검색어/.test(insText1), 'R1b 인스펙터에 검색어 노출')
  ok(/0건|관련 결과 0건|이 턴에서는 문서 검색/.test(insText1) || !/유사도 0\./.test(insText1),
    'R1c min=0.5 필터 → 저점수 문서 드롭(0건)')
  await page.screenshot({ path: `${OUT}/rag-thr-191-filtered.png` })

  // ── R2) API로 min=0 에이전트 → 히트 카드 + 범례 + 검색어 ──
  const cfgB = {
    model: 'mock-llm', prompt: a.prompt, memories: [], historyDepth: 10,
    vectorTables: ['docs-kb'], mcps: [], ragMinScores: {},
  }
  const created = await fetch(`${API}/agents`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: JSON.stringify({ name: `${NAME}-b`, config: cfgB }),
  })
  const bJson = await created.json().catch(() => ({}))
  idB = bJson?.id
  ok(!!idB, `R2a min=0 에이전트 생성(${NAME}-b)`)
  // 플레이그라운드 에이전트 목록은 페이지 로드 시 캐시됨 — API로 만든 B를 보려면 리로드.
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await selectAgent(`${NAME}-b`)
  const ta2 = page.locator('textarea').first()
  await ta2.click(); await ta2.fill('docs-kb 문서 검색해줘'); await ta2.press('Enter')
  ok(await waitFor(/인스펙터/, 25000), 'R2b 응답 도착')
  await openInspector()
  const insText2 = await page.locator('body').innerText()
  ok(/유사도 0~1/.test(insText2), 'R2c 유사도 척도 범례 노출("유사도 0~1")')
  ok(/유사도 0\.\d{3}/.test(insText2), 'R2d 히트 카드에 유사도 배지(점수)')
  ok(/검색어/.test(insText2), 'R2e 검색어 노출')
  await page.screenshot({ path: `${OUT}/rag-thr-191-cards.png`, fullPage: true })

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  for (const id of [idA, idB]) if (id) await fetch(`${API}/agents/${id}`, { method: 'DELETE', headers: { Cookie: cookie } }).catch(() => {})
  console.log('CLEANUP', [idA, idB].filter(Boolean).join(', ') || '(생성 실패)')
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (RAGTHR191_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
