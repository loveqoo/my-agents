/* 스펙 192 e2e — 인스펙터 단계(노드)별 실행 타임라인 개편.
   자원별 섹션 → 실행 노드 축으로 뒤집은 것을 실검증한다.
   T1) 인스펙터가 "실행 흐름" 탭 + 타임라인 노드(시작/모델 호출/도구·문서 검색 실행/종료)로 그려진다.
   T2) tools 노드 아래 문서검색 카드 — 검색어 + 커트라인 미달 문서("✗ 커트라인 … 미달 · 미사용")가 보인다
       (= "어떤 문서를 커트라인 미달로 못 썼나" 요구 충족).
   T3) "프롬프트·설정" 탭으로 전환 → 전송/시스템 프롬프트 접근 가능(무회귀).
   T4) "확대" → 전체화면 Modal(90vw)에 타임라인 재현(드로워 비좁음 해소).

   min=0.5 에이전트를 API로 만들어 mock-llm이 search_documents를 결정적으로 내게 한다(스펙 191 트리거).
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-node-timeline-192.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
const NAME = `nt192-${Date.now().toString(36)}`

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

let id = null
try {
  // ── 준비: min=0.5(docs-kb) 에이전트를 API로 생성 → mock 저점수 문서가 '미달'로 표시되게. ──
  const prompt = '너는 문서를 검색하는 조수다.'
  const created = await fetch(`${API}/agents`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: JSON.stringify({
      name: NAME,
      config: { model: 'mock-llm', prompt, memories: [], historyDepth: 10, vectorTables: ['docs-kb'], mcps: [], ragMinScores: { 'docs-kb': 0.5 } },
    }),
  })
  id = (await created.json().catch(() => ({})))?.id
  ok(!!id, `준비: min=0.5 에이전트 생성(${NAME})`)

  // ── 로그인 → 플레이그라운드 → 실행 ──
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await selectAgent(NAME)
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('docs-kb 문서 검색해줘'); await ta.press('Enter')
  ok(await waitFor(/인스펙터/, 25000), '응답 도착(인스펙터 링크)')
  await page.getByText('인스펙터', { exact: false }).last().click()
  await page.waitForTimeout(800)

  // ── T1) "실행 흐름" 탭 + 타임라인 노드 ──
  const tabFlow = await page.getByRole('tab', { name: '실행 흐름' }).count()
  ok(tabFlow > 0, 'T1a "실행 흐름" 탭 존재')
  const t1 = await page.locator('body').innerText()
  ok(/모델 호출/.test(t1), 'T1b 노드 라벨 "모델 호출"(model)')
  ok(/도구·문서 검색 실행/.test(t1), 'T1c 노드 라벨 "도구·문서 검색 실행"(tools)')
  ok(/종료/.test(t1), 'T1d 노드 라벨 "종료"(__end__)')
  // antd Timeline이 실제로 그려졌는지(구 GraphPath 텍스트 아님).
  const timelineItems = await page.locator('.ant-timeline-item').count()
  ok(timelineItems >= 3, `T1e antd Timeline 렌더(${timelineItems} items)`)

  // ── T2) tools 노드 아래: 검색어 + 커트라인 미달 문서("이용 못한") ──
  ok(/검색어/.test(t1), 'T2a 검색어 노출')
  ok(/커트라인.*미달|미달.*미사용/.test(t1), 'T2b 커트라인 미달 문서 표시("못 쓴 문서")')
  ok(/01-getting-started/.test(t1), 'T2c 미달이어도 문서 자체는 trace에 남음(파일명)')
  await page.screenshot({ path: `${OUT}/nt-192-timeline.png` })

  // ── T3) "프롬프트·설정" 탭 전환 → 프롬프트 접근(무회귀) ──
  await page.getByRole('tab', { name: '프롬프트·설정' }).click()
  await page.waitForTimeout(500)
  const t3 = await page.locator('body').innerText()
  ok(/전송 프롬프트|시스템 프롬프트/.test(t3), 'T3 프롬프트·설정 탭서 프롬프트 접근 가능')

  // ── T4) "확대" → 전체화면 Modal ──
  await page.getByRole('button', { name: '확대' }).click()
  await page.waitForTimeout(600)
  const modal = page.locator('.ant-modal').filter({ hasText: '턴 인스펙터' })
  ok(await modal.count() > 0, 'T4a "확대" → 전체화면 Modal 열림')
  const modalText = await modal.first().innerText().catch(() => '')
  ok(/실행 흐름|모델 호출|도구·문서 검색 실행/.test(modalText), 'T4b Modal에 타임라인 재현')
  // Modal 폭이 넓은지(90vw ≈ 1260px @1400) — 드로워(384) 대비 확장 확인.
  const box = await modal.first().boundingBox().catch(() => null)
  ok(!!box && box.width > 800, `T4c Modal 넓은 폭(${box ? Math.round(box.width) : '?'}px > 800)`)
  await page.screenshot({ path: `${OUT}/nt-192-fullscreen.png` })

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  if (id) await fetch(`${API}/agents/${id}`, { method: 'DELETE', headers: { Cookie: cookie } }).catch(() => {})
  console.log('CLEANUP', id || '(생성 실패)')
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (NODETIMELINE192_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
