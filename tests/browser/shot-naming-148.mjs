/* 스펙 148 e2e — 네이밍 규칙(식별 이름 vs 별명) 브라우저 검증.
   (K1) 에이전트 목록: 기존 "옵시디언 매니저"가 별명 우선 표시 + 식별 이름("옵시디언-매니저") 보조 표기.
   (K2) 에이전트 생성 모달: 식별 이름에 "My Agent"(공백+대문자, 규칙 위반) → 에러 힌트 + 확인 버튼 disabled.
   (K3) 식별 이름 "e2e-naming-148" + 별명 "E2E 네이밍 검증"로 고치면 버튼 활성화 → 생성 → 목록에 별명 표시.
   (K4) 목록 검색: 식별 이름 일부("e2e-naming")로도, 별명 일부("E2E 네이밍")로도 해당 행이 남는다.
   (K5) RAG 컬렉션 생성 모달: 식별 이름에 "Bad Name" → 빨간 힌트(생성은 하지 않고 취소).
   (K6) 정리: 생성한 에이전트를 드로어에서 삭제 → 목록에서 사라짐 확인.

   템플릿=shot-agents-ux-144.mjs(로그인·banner heading 대기·antd Modal/Drawer 셀렉터 관례,
   자체구현 Drawer는 제목이 순수 텍스트라 텍스트 매칭으로 존재 확인).
   앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-naming-148.mjs */
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_DIR = path.join(__dirname, 'out-148')
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const AGENT_ALIAS_EXISTING = '옵시디언 매니저'
const AGENT_NAME_EXISTING = '옵시디언-매니저'

const NEW_NAME = 'e2e-naming-148'
const NEW_ALIAS = 'E2E 네이밍 검증'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

const rowFor = (name) => page.locator('table tbody tr').filter({ hasText: name })

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

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

  // ---------- 사전 정리(멱등화): API로 잔여 NEW_NAME 삭제 ----------
  const listResp0 = await page.request.get(`${URL}/api/agents`)
  const arr0 = await listResp0.json()
  const stale = arr0.filter((a) => typeof a.name === 'string' && a.name.startsWith(NEW_NAME))
  for (const a of stale) await page.request.delete(`${URL}/api/agents/${a.id}`).catch(() => {})
  console.log(`(사전정리) 잔여 "${NEW_NAME}*" ${stale.length}건 제거`)
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ================= K1: 기존 에이전트 별명 우선 표시 + 식별 이름 보조 표기 =================
  // "옵시디언 매니저"는 owner_id가 설정된 private 에이전트(DB 실측) — 던짐용 super는 소유자가 아니므로
  // 기본 목록(ownerFilter=all)엔 안 보인다(스펙 147 — 타인 private는 opt-in). K1 전용으로 "소유: private ·
  // 타인(숨김 해제)"를 선택해 드러낸 뒤, 확인 후 다시 "전체"로 되돌려 이후 스텝(내 에이전트 검색)에 영향 없게 한다.
  // antd 6 이 Select 옵션은 role="option" 속성이 없다(실측: <div class="ant-select-item-option">,
  // title 속성에 라벨) — getByRole('option') 대신 class+title로 지목.
  // filter(hasText:'소유:')는 옵션 선택 후 표시값이 바뀌면(예: "private · 타인 (숨김 해제)") 더 이상
  // "소유:"를 포함하지 않아 재선택 시 매치가 깨진다 — 툴바 Select 렌더 순서(정렬·소유·소스·상태)로 고정 지목.
  const ownerSelect = page.locator('.ant-select').nth(1)
  await ownerSelect.click()
  await page.locator('.ant-select-item-option[title="private · 타인 (숨김 해제)"]').click()
  await page.waitForTimeout(400)

  const existingRow = rowFor(AGENT_ALIAS_EXISTING)
  const existingRowCount = await existingRow.count()
  let existingRowText = ''
  if (existingRowCount > 0) existingRowText = await existingRow.first().innerText()
  check(
    existingRowCount === 1 && existingRowText.includes(AGENT_ALIAS_EXISTING) && existingRowText.includes(AGENT_NAME_EXISTING),
    `K1: "${AGENT_ALIAS_EXISTING}" 행 존재(${existingRowCount}) + 보조 표기 "${AGENT_NAME_EXISTING}" 포함(실제 행 텍스트="${existingRowText.replace(/\n/g, ' | ')}")`
  )
  await shot('k1-list-existing')

  // K1 전용 필터 원복(전체) — 이후 스텝은 내가 만든 에이전트를 다뤄야 하므로.
  await ownerSelect.click()
  await page.locator('.ant-select-item-option[title="소유: 전체"]').click()
  await page.waitForTimeout(300)

  // ================= K2: 생성 모달 — 식별 이름 위반 시 에러 힌트 + 버튼 disabled =================
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  const createDialog = page.getByRole('dialog')
  await createDialog.locator('.ant-modal-title', { hasText: '에이전트 생성' }).waitFor({ timeout: 5000 })
  const nameInput = page.getByPlaceholder('예: research-assistant')
  const aliasInput = page.getByPlaceholder('예: 리서치 어시스턴트')
  const okBtn = createDialog.getByRole('button', { name: '에이전트 생성', exact: true })

  await nameInput.fill('My Agent')
  await page.waitForTimeout(200)
  const errHintCount = await createDialog.getByText(/이름 규칙 위반/).count()
  const okDisabledAfterBad = await okBtn.isDisabled()
  check(errHintCount > 0, `K2a: "My Agent" 입력 → 에러 힌트("이름 규칙 위반" 포함) 표시(개수=${errHintCount})`)
  check(okDisabledAfterBad, `K2b: 확인(생성) 버튼 disabled=${okDisabledAfterBad}`)
  await shot('k2-create-invalid')

  // ================= K3: 식별 이름/별명 고치면 버튼 활성화 → 생성 → 목록에 별명 표시 =================
  await nameInput.fill(NEW_NAME)
  await aliasInput.fill(NEW_ALIAS)
  await page.waitForTimeout(200)
  const okEnabledAfterFix = await okBtn.isEnabled()
  check(okEnabledAfterFix, `K3a: 식별 이름="${NEW_NAME}" + 별명="${NEW_ALIAS}" → 확인 버튼 활성화=${okEnabledAfterFix}`)
  await shot('k3-create-valid')
  await okBtn.click()
  await createDialog.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(600)

  const newRow = rowFor(NEW_ALIAS)
  const newRowCount = await newRow.count()
  check(newRowCount === 1, `K3b: 생성 후 목록에 별명 "${NEW_ALIAS}" 행 1개(실제=${newRowCount})`)
  await shot('k3-list-after-create')

  // ================= K4: 검색 — 식별 이름/별명 둘 다 매칭 =================
  const searchInput = page.getByPlaceholder('이름·모델·소스 검색')
  await searchInput.fill('e2e-naming')
  await page.waitForTimeout(300)
  const byNameCount = await rowFor(NEW_ALIAS).count()
  check(byNameCount === 1, `K4a: 검색어 "e2e-naming"(식별 이름) → 해당 행 남음(실제=${byNameCount})`)
  await shot('k4a-search-by-name')

  await searchInput.fill('')
  await page.waitForTimeout(200)
  await searchInput.fill('E2E 네이밍')
  await page.waitForTimeout(300)
  const byAliasCount = await rowFor(NEW_ALIAS).count()
  check(byAliasCount === 1, `K4b: 검색어 "E2E 네이밍"(별명) → 해당 행 남음(실제=${byAliasCount})`)
  await shot('k4b-search-by-alias')

  await searchInput.fill('')
  await page.waitForTimeout(300)

  // ================= K5: RAG 컬렉션 생성 모달 — 식별 이름 위반 시 빨간 힌트(생성하지 않고 취소) =================
  await page.getByRole('menuitem', { name: 'RAG 컬렉션' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: 'RAG 컬렉션' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)

  // 아이콘 버튼 접근성 이름은 "plus 컬렉션 생성"처럼 아이콘 라벨+텍스트가 합쳐진다(144 학습) — 정규식 매치.
  const collCreateBtn = page.getByRole('button', { name: /컬렉션 생성/ })
  const collCreateBtnDisabled = await collCreateBtn.isDisabled().catch(() => true)
  if (collCreateBtnDisabled) {
    check(false, 'K5: "컬렉션 생성" 버튼이 disabled(임베딩 모델 미등록 추정) — 모달을 열 수 없어 검증 불가')
  } else {
    await collCreateBtn.click()
    const collDialog = page.getByRole('dialog')
    await collDialog.locator('.ant-modal-title', { hasText: '컬렉션 생성' }).waitFor({ timeout: 5000 })
    const collNameInput = page.getByPlaceholder('예: docs-kb')
    await collNameInput.fill('Bad Name')
    await page.waitForTimeout(200)
    const collErrHint = collDialog.getByText(/이름 규칙 위반/)
    const collErrHintCount = await collErrHint.count()
    let redColorOk = false
    if (collErrHintCount > 0) {
      const color = await collErrHint.first().evaluate((el) => getComputedStyle(el).color)
      // var(--red-6) 계열 — 빨간 계열(R값이 G/B보다 뚜렷이 큼)인지로 판정.
      const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color)
      redColorOk = !!m && parseInt(m[1], 10) > 150 && parseInt(m[1], 10) > parseInt(m[2], 10) + 40
      check(collErrHintCount > 0, `K5a: "Bad Name" 입력 → 에러 힌트("이름 규칙 위반" 포함) 표시(개수=${collErrHintCount})`)
      check(redColorOk, `K5b: 힌트 텍스트 색상이 빨간 계열(실측 color="${color}")`)
    } else {
      check(false, 'K5a: "Bad Name" 입력 → 에러 힌트 미표시(FAIL)')
      check(false, 'K5b: 힌트 색상 확인 불가(힌트 자체가 없음)')
    }
    await shot('k5-collection-create-invalid')
    await collDialog.getByRole('button', { name: '취소', exact: true }).click()
    await collDialog.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(400)
  }

  // ================= K6: 정리 — 드로어에서 생성한 에이전트 삭제 =================
  await gotoAgents()
  await rowFor(NEW_ALIAS).first().click()
  const delBtn = page.getByRole('button', { name: /삭제/ })
  await delBtn.waitFor({ timeout: 8000 })
  await delBtn.click()
  const confirmDialog = page.getByRole('dialog')
  await confirmDialog.getByText('에이전트를 삭제할까요?', { exact: true }).waitFor({ timeout: 5000 })
  await confirmDialog.getByRole('button', { name: '삭제', exact: true }).click()
  await page.waitForTimeout(800)
  const remaining = await rowFor(NEW_ALIAS).count()
  check(remaining === 0, `K6: 정리 — 목록에서 "${NEW_ALIAS}" 사라짐(잔여 행=${remaining})`)
  await shot('k6-list-after-delete')

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
} finally {
  // best-effort 잔여 정리(테스트 실패로 중도 종료해도 다음 실행이 안 새게).
  try {
    const listResp1 = await page.request.get(`${URL}/api/agents`)
    const arr1 = await listResp1.json()
    for (const a of arr1.filter((x) => typeof x.name === 'string' && x.name.startsWith(NEW_NAME))) {
      await page.request.delete(`${URL}/api/agents/${a.id}`).catch(() => {})
    }
  } catch { /* best effort */ }
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
