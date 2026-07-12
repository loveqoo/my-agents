/* 스펙 316 프론트 기능 검증 — 노드 라이브러리(외형 아닌 동작: 실제 수행→효과를 API/DB로 단언).
   ① API로 템플릿 v1 발행 → "노드 라이브러리" 메뉴에 목록(이름·v1)·Drawer 버전 히스토리.
   ② Drawer "이 버전으로 새 버전 발행" → 발행 → API로 2개 버전 확인(UI 발행의 효과 단언).
   ③ 에이전트 폼: 노드형 → 노드 추가 → Segmented "라이브러리 참조" → 이름/버전 선택 → 해석
      미리보기 노출 → 저장 → **API로 config.nodes==[{ref}] + resolvedNodes 해석 확인**.
   ④ Drawer 재진입: 참조된 버전의 삭제 버튼 disabled(가드 표면화) + usedBy에 에이전트 이름.
   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-316-node-library-ui.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()

const TPL = `v316ui-${Date.now().toString(36)}`
const AGENT = `v316ui-pipe-${Date.now().toString(36)}`
const V1_PROMPT = '들어온 요청을 한 줄로 요약해라'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]
const api = (path, init = {}) =>
  fetch(`${API}${path}`, { ...init, headers: { 'Content-Type': 'application/json', Cookie: cookie, ...(init.headers || {}) } })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1100 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

let agentId = null
try {
  // ── ① API로 v1 발행 → 라이브러리 뷰에 반영 ──
  const r1 = await api('/node-templates', {
    method: 'POST',
    body: JSON.stringify({ name: TPL, description: '요약 노드', config: { name: '요약', prompt: V1_PROMPT, model: 'mock-llm' } }),
  })
  check(r1.status === 201, `① API 템플릿 v1 발행 201 (got ${r1.status})`)

  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)

  await page.getByText('노드 라이브러리', { exact: true }).first().click()
  await page.waitForTimeout(800)
  const listText = await page.locator('body').innerText()
  check(listText.includes(TPL), '① 목록에 템플릿 이름')
  check(/v1/.test(listText), '① 목록에 최신 버전 v1')

  // Drawer 열기
  await page.getByText(TPL, { exact: false }).first().click()
  await page.waitForTimeout(700)
  const drawer = page.locator('.ant-drawer:visible').last()
  const drawerText = await drawer.innerText()
  check(drawerText.includes(V1_PROMPT.slice(0, 10)), '① Drawer에 config 요약(프롬프트 앞부분)')

  // ── ② UI로 새 버전 발행 → API로 효과 단언 ──
  const publishBtn = drawer.getByRole('button', { name: /새 버전/ }).first()
  if (await publishBtn.isVisible().catch(() => false)) {
    await publishBtn.click()
    await page.waitForTimeout(600)
    const modal = page.locator('.ant-modal:visible').last()
    const ta = modal.locator('textarea').first()
    await ta.fill('v2: 들어온 요청을 세 줄로 요약해라')
    await modal.getByRole('button', { name: /발행|등록|생성|저장/ }).last().click()
    await page.waitForTimeout(1200)
    const det = await (await api(`/node-templates/${TPL}`)).json()
    check((det.versions || []).length === 2 && det.versions[0].version === 2,
      `② UI 발행 → API에 v2 (got ${(det.versions || []).map((v) => v.version)})`)
  } else {
    check(false, '② Drawer에 "새 버전 발행" 버튼이 보여야 함')
  }
  // Drawer 닫기(발행 모달이 이미 닫힌 뒤 — 닫기 버튼 직접 클릭, 마스크 잔존 방지)
  await page.locator('.ant-drawer:visible .ant-drawer-close').last().click().catch(() => {})
  await page.waitForTimeout(300)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)

  // ── ③ 에이전트 폼: 라이브러리 참조로 노드 구성 → 저장 → API 단언 ──
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const typeField = page.locator('label', { hasText: '에이전트 종류' }).first()
  await typeField.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
  await page.getByPlaceholder('예: research-assistant').fill(AGENT)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(500)

  const modal = page.locator('.ant-modal:visible').last()
  // Segmented "라이브러리 참조" 전환
  const seg = modal.locator('.ant-segmented-item', { hasText: '라이브러리' }).first()
  check(await seg.isVisible().catch(() => false), '③ 노드 카드에 "직접 설정|라이브러리 참조" Segmented')
  await seg.click()
  await page.waitForTimeout(500)
  // 이름 Select → 템플릿 선택
  const refSelects = modal.locator('.ant-collapse .ant-select')
  await refSelects.first().click()
  await page.waitForTimeout(400)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: TPL }).first().click()
  await page.waitForTimeout(800)
  const cardText = await modal.locator('.ant-collapse').first().innerText()
  check(cardText.includes('세 줄') || cardText.includes(V1_PROMPT.slice(0, 8)), `③ 해석 미리보기 노출 (got ${JSON.stringify(cardText.slice(0, 140))})`)

  // 저장(남은 스텝 통과)
  for (let i = 0; i < 6; i++) {
    const createBtn = page.getByRole('button', { name: '에이전트 생성' })
    if (await createBtn.isVisible().catch(() => false)) { await createBtn.click(); break }
    const next = page.getByRole('button', { name: '다음' }).last()
    if (await next.isVisible().catch(() => false)) { await next.click(); await page.waitForTimeout(500) }
  }
  await page.waitForTimeout(1500)
  const agents = await (await api('/agents')).json()
  const saved = agents.find((a) => a.name === AGENT)
  agentId = saved?.id ?? null
  const refNode = saved?.nodes?.[0]
  check(!!saved, '③ 저장: 에이전트 생성됨')
  check(!!refNode && !!refNode.ref && refNode.ref.name === TPL, `③ 저장: nodes=[{ref}] (got ${JSON.stringify(refNode)})`)
  check(Array.isArray(saved?.resolvedNodes) && typeof saved.resolvedNodes[0]?.prompt === 'string',
    `③ 저장: resolvedNodes 해석 (got ${JSON.stringify(saved?.resolvedNodes?.[0]?.prompt ?? null)})`)

  // ── ④ 참조된 버전 삭제 버튼 disabled + usedBy 표면화 ──
  await page.getByText('노드 라이브러리', { exact: true }).first().click()
  await page.waitForTimeout(700)
  await page.getByText(TPL, { exact: false }).first().click()
  await page.waitForTimeout(700)
  const drawer2 = page.locator('.ant-drawer:visible').last()
  const d2 = await drawer2.innerText()
  check(d2.includes(AGENT), `④ Drawer usedBy에 참조 에이전트 (got ${JSON.stringify(d2.slice(0, 60))}...)`)
  const refVersion = saved?.nodes?.[0]?.ref?.version
  // 참조된 버전 블록의 삭제 버튼이 disabled인지 — 삭제 버튼 전수 중 최소 1개 disabled(참조 버전).
  const delBtns = drawer2.getByRole('button', { name: /삭제/ })
  const n = await delBtns.count()
  let anyDisabled = false
  for (let i = 0; i < n; i++) if (await delBtns.nth(i).isDisabled().catch(() => false)) anyDisabled = true
  check(n > 0 && anyDisabled, `④ 참조 버전 삭제 버튼 disabled (buttons=${n}, refVersion=${refVersion})`)

  check(pageErrors.length === 0, `페이지 JS 에러 0 (got ${pageErrors.slice(0, 2)})`)
} finally {
  if (agentId) await api(`/agents/${agentId}`, { method: 'DELETE' }).catch(() => {})
  // 템플릿 정리(참조 삭제 후 전 버전)
  const det = await (await api(`/node-templates/${TPL}`)).json().catch(() => null)
  for (const v of det?.versions ?? []) await api(`/node-templates/${TPL}/${v.version}`, { method: 'DELETE' }).catch(() => {})
  await browser.close()
}

console.log(`\n${fails.length} failed`)
if (fails.length) { for (const f of fails) console.log('  FAILED:', f); process.exit(1) }
console.log('VERIFY316_UI_OK — 노드 라이브러리 UI(목록·발행·참조 구성·저장·가드) 기능 정착')
