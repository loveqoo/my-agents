/* 스펙 144 e2e — 에이전트 메뉴 UX 보완 3건.
   (U1) 리스트 검색/정렬: 검색 Input("이름·모델·소스 검색") + 정렬 Select("이름순") 존재, 타이핑 →
        행 필터 + "N/M개" 카운터, 지우면 전체 복귀.
   (U2) 컬럼 상시 표시: 뷰포트를 900×800으로 줄여도 thead th 개수가 1400px일 때와 동일(hideBelow로
        컬럼이 숨지 않고 가로 스크롤로 유지 — DataTable에 hideBelow 지정 없음, 표 자체는 overflow-x:auto).
   (U3) 편집→드로워 복귀: "편집(새 초안)" → 이름에 " v2" 추가 → 저장 → 리스트가 아니라 그 에이전트의
        드로워로 복귀(제목+"활성화" 버튼). 취소 경로도 1회 확인(편집 열고 취소 → 드로워 복귀).
   (U4) 테스트→플레이그라운드: 드로워 "테스트" 클릭 → 화면이 Playground로 전환되고(헤더 h3="Playground")
        그 에이전트가 선택돼(피커 트리거에 이름 표시) 있어야 — 토스트만 뜨고 화면 전환 없으면 FAIL.
   (U5) 정리: 편집된 에이전트("...v2") 삭제 → 목록에서 사라짐.

   템플릿=shot-eval-golden-142.mjs(로그인·banner heading 대기·antd Modal/Select 셀렉터 관례,
   dialog로 스코프 고정해 동일 라벨 버튼 중복 방지) + shot-clone-120.mjs(API pre-clean/cleanup 패턴).
   이 프로젝트의 Drawer는 antd Drawer가 아니라 자체 구현(admin/shared.tsx `Drawer` — position:fixed
   오버레이, 제목은 순수 <span>이라 accessible name 없음) — 존재 확인은 텍스트 매칭으로.

   앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-agents-ux-144.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/agents-144.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const AGENT_NAME = 'e2e-144-봇'
const AGENT_NAME_V2 = `${AGENT_NAME} v2`

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

const rowFor = (name) => page.locator('table tbody tr').filter({ hasText: name })

async function gotoAgents() {
  await page.getByRole('menuitem', { name: '에이전트' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- 사전 정리(멱등화): API로 잔여 "e2e-144-봇"(*, v2 포함) 삭제 ----------
  const listResp0 = await page.request.get(`${URL}/api/agents`)
  const arr0 = await listResp0.json()
  const stale = arr0.filter((a) => typeof a.name === 'string' && a.name.startsWith(AGENT_NAME))
  for (const a of stale) await page.request.delete(`${URL}/api/agents/${a.id}`).catch(() => {})
  console.log(`(사전정리) 잔여 "${AGENT_NAME}*" ${stale.length}건 제거`)
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- U0 준비: "새 에이전트" → 이름만 입력 → 기본값 저장 ----------
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  const createDialog = page.getByRole('dialog')
  await createDialog.locator('.ant-modal-title', { hasText: '에이전트 생성' }).waitFor({ timeout: 5000 })
  await page.getByPlaceholder('예: 리서치 어시스턴트').fill(AGENT_NAME)
  await createDialog.getByRole('button', { name: '에이전트 생성', exact: true }).click()
  await createDialog.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(600)
  const createdCount = await rowFor(AGENT_NAME).count()
  check(createdCount === 1, `U0: "${AGENT_NAME}" 생성 → 목록에 1행(실제=${createdCount})`)

  // ---------- U1: 검색/정렬 ----------
  const searchInput = page.getByPlaceholder('이름·모델·소스 검색')
  const sortSelect = page.locator('.ant-select').filter({ hasText: '이름순' })
  check((await searchInput.count()) > 0, 'U1a: 검색 Input("이름·모델·소스 검색") 존재')
  check((await sortSelect.count()) > 0, 'U1b: 정렬 Select("이름순") 존재')

  const toolbarCounter = () => page.locator('xpath=//input[@placeholder="이름·모델·소스 검색"]/ancestor::div[1]')
  const baselineText = await toolbarCounter().innerText()
  const baselineMatch = /(\d+)\/(\d+)개/.exec(baselineText)
  const baselineTotal = baselineMatch ? parseInt(baselineMatch[2], 10) : -1
  check(!!baselineMatch && baselineMatch[1] === baselineMatch[2], `U1c: 검색 전 카운터 "N/N개"(실제="${baselineMatch?.[0]}")`)

  await searchInput.fill('e2e-144')
  await page.waitForTimeout(300)
  const filteredCount = await rowFor(AGENT_NAME).count()
  const totalRowsFiltered = await page.locator('table tbody tr').count()
  const filteredText = await toolbarCounter().innerText()
  const filteredMatch = /(\d+)\/(\d+)개/.exec(filteredText)
  check(
    totalRowsFiltered === 1 && filteredCount === 1 && !!filteredMatch && filteredMatch[1] === '1' && filteredMatch[2] === String(baselineTotal),
    `U1d: "e2e-144" 검색 → 행 1개(실제 표 행=${totalRowsFiltered}) + 카운터="${filteredMatch?.[0]}"(기대 1/${baselineTotal})`
  )

  await searchInput.fill('')
  await page.waitForTimeout(300)
  const restoredRows = await page.locator('table tbody tr').count()
  const restoredText = await toolbarCounter().innerText()
  const restoredMatch = /(\d+)\/(\d+)개/.exec(restoredText)
  check(
    restoredRows === baselineTotal && !!restoredMatch && restoredMatch[1] === restoredMatch[2],
    `U1e: 검색어 지움 → 전체 복귀(행=${restoredRows}, 기대=${baselineTotal}) + 카운터="${restoredMatch?.[0]}"`
  )

  // ---------- U2: 컬럼 상시 표시(뷰포트 900×800에서도 th 개수 동일) ----------
  const thCountWide = await page.locator('table thead th').count()
  await page.setViewportSize({ width: 900, height: 800 })
  await page.waitForTimeout(400)
  const thCountNarrow = await page.locator('table thead th').count()
  check(
    thCountNarrow === thCountWide && thCountWide > 0,
    `U2: 900×800에서도 컬럼 개수 유지(1400px=${thCountWide}, 900px=${thCountNarrow})`
  )
  await page.setViewportSize({ width: 1400, height: 1100 })
  await page.waitForTimeout(400)

  // ---------- U3: 편집 → 드로워 복귀 ----------
  // antd Icon 컴포넌트가 role="img" aria-label(예:"edit"/"delete"/"check")을 내므로 아이콘 있는
  // 버튼의 접근성 이름은 "edit 초안 편집"처럼 아이콘 라벨+텍스트가 합쳐진다 — exact 매치 대신 정규식
  // 사용(shot-agent-create.mjs류 템플릿엔 없던 이 프로젝트 특유 함정, 직접 실측 확인).
  // 새로 생성된 에이전트의 v1은 이미 미활성 초안 상태로 시작한다(생성 시 활성화까지는 안 함 —
  // "v1 초안, 테스트 후 활성화" 토스트와 일치) → 드로워 풋터 편집 버튼은 처음부터 "초안 편집"(초안이
  // 이미 있으므로 "편집(새 초안)" 라벨은 이 시나리오에선 뜨지 않는다).
  await rowFor(AGENT_NAME).first().click()
  const editFirstBtn = page.getByRole('button', { name: /초안 편집/ })
  await editFirstBtn.waitFor({ timeout: 8000 })
  await editFirstBtn.click()
  const editDialog = page.getByRole('dialog')
  const editNameInput = page.getByPlaceholder('예: 리서치 어시스턴트')
  await editNameInput.waitFor({ timeout: 5000 })
  const curName = await editNameInput.inputValue()
  check(curName === AGENT_NAME, `U3 준비: 편집 폼 이름 프리필="${curName}"(기대="${AGENT_NAME}")`)
  await editNameInput.fill(AGENT_NAME_V2)
  await editDialog.getByRole('button', { name: '초안 저장', exact: true }).click()
  await editDialog.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(600)

  const drawerHasV2AfterSave = (await page.getByText(AGENT_NAME_V2, { exact: true }).count()) > 0
  const activateVisibleAfterSave = (await page.getByRole('button', { name: /활성화/ }).count()) > 0
  check(
    drawerHasV2AfterSave && activateVisibleAfterSave,
    `U3a: 저장 후 리스트 아닌 드로워 복귀 — "${AGENT_NAME_V2}" 텍스트(${drawerHasV2AfterSave}) + "활성화" 버튼(${activateVisibleAfterSave})`
  )

  // ---------- U3 취소 경로 ----------
  const editAgainBtn = page.getByRole('button', { name: /초안 편집/ })
  await editAgainBtn.waitFor({ timeout: 8000 })
  await editAgainBtn.click()
  const cancelDialog = page.getByRole('dialog')
  await cancelDialog.getByText('초안 편집', { exact: false }).first().waitFor({ timeout: 5000 })
  await cancelDialog.getByRole('button', { name: '취소', exact: true }).click()
  await cancelDialog.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(500)
  const drawerHasV2AfterCancel = (await page.getByText(AGENT_NAME_V2, { exact: true }).count()) > 0
  const activateVisibleAfterCancel = (await page.getByRole('button', { name: /활성화/ }).count()) > 0
  check(
    drawerHasV2AfterCancel && activateVisibleAfterCancel,
    `U3b: 편집 취소 → 드로워 복귀 유지 — "${AGENT_NAME_V2}" 텍스트(${drawerHasV2AfterCancel}) + "활성화" 버튼(${activateVisibleAfterCancel})`
  )

  // ---------- U4: 테스트 → 플레이그라운드 전환 + 에이전트 선택 ----------
  // "테스트"/"활성화" 버튼은 드로워 상단 초안 박스(gold)와 하단 버전 히스토리 행에 중복 렌더된다
  // (VersionHistory가 draft 버전에 동일 액션을 다시 그림) — 클릭은 gold 박스로 스코프해 strict-mode
  // 다중 매치를 피한다.
  const draftBox = page.locator('div[style*="border: 1px solid var(--gold-3)"]')
  await draftBox.getByRole('button', { name: /테스트/ }).click()
  await page.locator('.ant-layout-header h3', { hasText: 'Playground' }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(600)
  const headerIsPlayground = (await page.locator('.ant-layout-header h3', { hasText: 'Playground' }).count()) > 0
  const agentSelectedInPlayground = (await page.getByText(AGENT_NAME_V2, { exact: false }).count()) > 0
  check(
    headerIsPlayground && agentSelectedInPlayground,
    `U4: Playground 화면 전환(${headerIsPlayground}) + "${AGENT_NAME_V2}" 선택 표시(${agentSelectedInPlayground})`
  )

  // ---------- 스크린샷(사용자 확인용) ----------
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)

  // ---------- 정리: 에이전트 메뉴 복귀 → "e2e-144-봇 v2" 삭제 ----------
  await gotoAgents()
  await rowFor(AGENT_NAME_V2).first().click()
  const delBtn = page.getByRole('button', { name: /삭제/ })
  await delBtn.waitFor({ timeout: 8000 })
  await delBtn.click()
  const confirmDialog = page.getByRole('dialog')
  await confirmDialog.getByText('에이전트를 삭제할까요?', { exact: true }).waitFor({ timeout: 5000 })
  await confirmDialog.getByRole('button', { name: '삭제', exact: true }).click()
  await page.waitForTimeout(800)
  const remaining = await rowFor(AGENT_NAME_V2).count()
  check(remaining === 0, `U5: 정리 — 목록에서 "${AGENT_NAME_V2}" 사라짐(잔여 행=${remaining})`)

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  // best-effort 잔여 정리(테스트 실패로 중도 종료해도 다음 실행이 안 새게).
  try {
    const listResp1 = await page.request.get(`${URL}/api/agents`)
    const arr1 = await listResp1.json()
    for (const a of arr1.filter((x) => typeof x.name === 'string' && x.name.startsWith(AGENT_NAME))) {
      await page.request.delete(`${URL}/api/agents/${a.id}`).catch(() => {})
    }
  } catch { /* best effort */ }
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
