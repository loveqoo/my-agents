/* 스펙 190 — 노코드 산출물형 에이전트 e2e.
   U) 어드민 폼: 종류=산출물형 → 필드 편집기 → 항목 추가(선택지 필드) → 저장.
   P) API 왕복: 생성된 에이전트 config.artifactSpec 보존 확인(폼 재로드 무손실).
   R) 플레이그라운드: 실행 → 동적 폼 → 제출 → artifact 카드(chat.py impl_config 배선 실검증). */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-loveqoo-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'
const NAME = `nocode-${Date.now().toString(36)}`

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

const waitFor = async (pattern, timeout = 25000) => {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    if (pattern.test(await page.locator('#root').innerText())) return true
    await page.waitForTimeout(600)
  }
  return false
}
// antd Select: 컨트롤 클릭 → **열린 드롭다운 한정**으로 옵션 클릭(닫힌 드롭다운의 잔존 옵션 오클릭 방지)
const pickSelect = async (control, optionText) => {
  await control.click()
  const dd = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').last()
  await dd.waitFor({ state: 'visible', timeout: 5000 })
  await dd.locator('.ant-select-item-option', { hasText: optionText }).first().click()
  await page.waitForTimeout(250)
}

let createdId = null
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // ── U) 폼으로 노코드 산출물형 저작 ──
  await page.getByRole('button', { name: '새 에이전트' }).first().click()
  await page.waitForTimeout(600)
  await page.getByPlaceholder('예: research-assistant').fill(NAME)
  // 종류 = 산출물형 (모달은 body 포털이라 #root 스캔 대신 locator로 검증)
  const typeSelect = page.locator('.ant-select').filter({ hasText: /직접 응답|조율형|산출물형/ }).first()
  await pickSelect(typeSelect, '산출물형')
  let editorShown = true
  await page.getByText('모을 항목', { exact: true }).first().waitFor({ timeout: 8000 }).catch(() => { editorShown = false })
  ok(editorShown, 'U1 종류=산출물형 → 필드 편집기 노출')
  // 항목 1: 선택지 필드(구매이력)
  await page.getByRole('button', { name: /항목 추가/ }).click()
  await page.waitForTimeout(300)
  await page.getByPlaceholder(/항목 이름/).first().fill('구매이력')
  await page.getByPlaceholder('결과 키').first().fill('purchase')
  const typeCol = page.locator('.ant-select').filter({ hasText: /자유 입력|선택지/ }).first()
  await pickSelect(typeCol, '선택지 중 고르기')
  // antd Select mode="tags" — placeholder는 오버레이 span이라 getByPlaceholder 불가. 검색 input에 직접 타이핑.
  const tagBox = page.locator('.ant-select-multiple').first()
  await tagBox.waitFor({ state: 'visible', timeout: 5000 })
  for (const c of ['최근', '7일 전', '최근 한 달']) {
    await tagBox.click()
    await page.keyboard.type(c)
    await page.keyboard.press('Enter')
    await page.waitForTimeout(150)
  }
  let tagsShown = true
  await page.getByText('최근 한 달', { exact: true }).first().waitFor({ timeout: 6000 }).catch(() => { tagsShown = false })
  ok(tagsShown, 'U2 선택지 3개 입력(태그)')
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  // 저장 성공 = 모달 래퍼가 사라짐(마스크 걷힘). 여러 antd 버전 대비 wrap/mask 중 먼저 숨는 것 대기.
  let saved = true
  await page.locator('.ant-modal-wrap').first().waitFor({ state: 'hidden', timeout: 12000 }).catch(() => { saved = false })
  ok(saved, 'U3 저장 후 모달 닫힘')
  await page.waitForTimeout(1000)

  // ── P) API 왕복: artifactSpec 보존 ──
  const agents = await (await fetch(`${API}/agents`, { headers: { Cookie: cookie } })).json()
  const created = (Array.isArray(agents) ? agents : []).find((a) => a.name === NAME)
  ok(!!created, `P1 에이전트 생성됨 (${NAME})`)
  createdId = created?.id
  ok(created?.impl === 'artifact_form', `P2 impl=artifact_form (got ${created?.impl})`)
  const specFields = created?.artifactSpec?.fields || []
  ok(specFields.length === 1 && specFields[0].key === 'purchase'
    && JSON.stringify(specFields[0].candidates) === JSON.stringify(['최근', '7일 전', '최근 한 달']),
    `P3 artifactSpec 왕복 보존 (got ${JSON.stringify(created?.artifactSpec)})`)

  // ── R) 플레이그라운드 실행 → 폼 → 제출 → artifact ──
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  const combo = page.locator('button').filter({ hasText: /research-assistant|에이전트/ }).first()
  await combo.click(); await page.waitForTimeout(400)
  await page.getByText(NAME, { exact: false }).first().click()
  await page.waitForTimeout(500)
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('시작할게'); await ta.press('Enter')
  ok(await waitFor(/입력이 필요합니다|구매이력/), 'R1 실행 → 동적 폼(설정한 항목)')
  await page.screenshot({ path: `${OUT}/nocode-190-form.png` })
  // 후보 Select에서 값 선택
  const formSel = page.locator('.ant-select').filter({ hasText: /구매이력|선택|최근/ }).first()
  if (await formSel.count()) await pickSelect(formSel, '최근 한 달')
  await page.getByRole('button', { name: '제출', exact: true }).click()
  ok(await waitFor(/산출물|purchase/), 'R2 제출 → artifact 카드')
  ok(await waitFor(/최근 한 달/), 'R3 artifact에 선택값 반영')
  await page.screenshot({ path: `${OUT}/nocode-190-artifact.png` })

  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  if (createdId) await fetch(`${API}/agents/${createdId}`, { method: 'DELETE', headers: { Cookie: cookie } }).catch(() => {})
  console.log('CLEANUP', createdId || '(생성 실패)')
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (NOCODE190_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
