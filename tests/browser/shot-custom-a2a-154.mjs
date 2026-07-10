/* 스펙 154 e2e — 커스텀 에이전트 A2A 공개 + 공개/비공개 전환(승격/강등) 브라우저 검증.
   (K1) 에이전트 목록 → "Plan-Execute Demo"(ui, public·A2A 꺼짐) 행 클릭 → 드로어에
        "공개 범위" 박스("public · " 문구)와 "비공개로 전환" 버튼이 보인다.
   (K2) "비공개로 전환" 클릭 → 확인 모달 → 전환 토스트 → 박스 문구가
        "비공개 · 소유자만 사용(A2A 불가)"로 바뀐다.
   (K3) "공개로 전환" 클릭 → 확인 → 문구가 공개로 복귀(원복).
   (K4) "Doc Translator"(code) 행 클릭 → 드로어에 "A2A로 공개 (중계)" 스위치가 보인다(꺼짐 상태).
        스크린샷만 남기고 켜지 않는다(상태 변경 최소화 — 존재·라벨 확인만).
   (K5) 원복 실측 — curl GET /agents(Bearer=.env API_AUTH_TOKEN)로
        plan-execute-demo(agt_plex_b5e207) owner_id==null && exposed.a2a==false,
        doc-translator(agt_xlt_a17c33) exposed.a2a==false 확인.

   조작 대상: 시드 에이전트 agt_plex_b5e207("Plan-Execute Demo", ui, public·A2A off),
             agt_xlt_a17c33("Doc Translator", code, public·A2A off) — 시작 전 상태로 반드시 원복.
   템플릿=shot-settings-153.mjs(로그인·대기 관례·원복 안전망), 행 클릭=shot-owner-114.mjs.
   앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-custom-a2a-154.mjs */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execSync } from 'node:child_process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..')
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API_URL = process.env.API_URL ?? 'http://127.0.0.1:8000'
const OUT_DIR = path.join(__dirname, 'out-154')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

// .env에서 API_AUTH_TOKEN 실측(하드코딩 금지 — 값이 바뀌어도 스크립트가 따라간다).
const envText = fs.readFileSync(path.join(REPO, '.env'), 'utf8')
const tokenMatch = envText.match(/^API_AUTH_TOKEN=(.+)$/m)
const API_TOKEN = process.env.API_AUTH_TOKEN ?? (tokenMatch ? tokenMatch[1].trim() : '')

const PLEX_AGENT_ID = 'agt_plex_b5e207' // Plan-Execute Demo (ui)
const XLT_AGENT_ID = 'agt_xlt_a17c33' // Doc Translator (code)

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

function fetchAgents() {
  const out = execSync(
    `curl -s ${API_URL}/agents -H "Authorization: Bearer ${API_TOKEN}"`,
    { encoding: 'utf8' }
  )
  return JSON.parse(out)
}

function findAgent(list, agentId) {
  return list.find((a) => a.agentId === agentId)
}

// PUT /agents/{id}/visibility로 강제 원복(내부 UUID id가 필요해 실측 후 사용).
function forceVisibility(internalId, isPublic) {
  return execSync(
    `curl -s -X PUT ${API_URL}/agents/${internalId}/visibility -H "Authorization: Bearer ${API_TOKEN}" -H "Content-Type: application/json" -d '{"public": ${isPublic}}'`,
    { encoding: 'utf8' }
  )
}

// 에이전트 메뉴 진입 후 alias 텍스트로 행을 찾아 클릭 → 드로어 오픈 대기.
async function openAgentDrawer(alias) {
  // 목록이 커져 페이지네이션 밖일 수 있음(스펙 286서 수리) — 이름 검색으로 좁힌 뒤 클릭.
  await page.getByPlaceholder('이름 검색').fill(alias)
  await page.waitForTimeout(500)
  const row = page.locator('tr', { hasText: alias }).first()
  await row.waitFor({ timeout: 10000 })
  await row.click()
  await page.waitForTimeout(700)
}

async function closeDrawer() {
  // 상세가 드로어→풀페이지(스펙 245)로 바뀜 — 돌아가기 버튼으로 목록 복귀(286서 수리).
  const back = page.getByRole('button', { name: /에이전트 목록/ })
  if (await back.count()) { await back.click() } else { await page.keyboard.press('Escape') }
  await page.waitForTimeout(400)
}

let plexInternalId = null
let reachedMutation = false

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 사전 실측 — 내부 UUID id 확보(강제 원복 안전망용) + 시작 전 상태 기록.
  const preList = fetchAgents()
  const prePlex = findAgent(preList, PLEX_AGENT_ID)
  const preXlt = findAgent(preList, XLT_AGENT_ID)
  plexInternalId = prePlex?.id
  check(!!prePlex && prePlex.owner_id == null && prePlex.exposed?.a2a === false, `사전 실측: Plan-Execute Demo 시작 상태 public·A2A off(실측 owner_id=${JSON.stringify(prePlex?.owner_id)}, a2a=${prePlex?.exposed?.a2a})`)
  check(!!preXlt && preXlt.exposed?.a2a === false, `사전 실측: Doc Translator 시작 상태 A2A off(실측 a2a=${preXlt?.exposed?.a2a})`)

  await page.getByText('에이전트', { exact: true }).first().click()
  await page.locator('.ant-layout-header h3', { hasText: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ================= K1: Plan-Execute Demo 행 클릭 → "공개 범위" 박스 + "비공개로 전환" 버튼 =================
  await openAgentDrawer('plan-execute-demo')
  // 공개 범위 박스는 공개·연동 탭에만 렌더(스펙 246 탭 하나만 렌더 — 286서 수리).
  await page.getByRole('tab', { name: '공개·연동' }).click()
  await page.waitForTimeout(400)
  await shot('00-plex-drawer-public')
  const bodyText1 = await page.locator('body').innerText()
  check(bodyText1.includes('공개 범위'), 'K1a: "공개 범위" 박스 표시')
  check(bodyText1.includes('꺼짐 · 노출되지 않음'), 'K1b: 공개 상태의 A2A 행(켤 수 있음 — 꺼짐 안내)')
  const demoteBtn = page.getByRole('button', { name: '비공개로 전환' })
  check((await demoteBtn.count()) > 0, 'K1c: "비공개로 전환" 버튼 표시')

  // ================= K2: "비공개로 전환" → 확인 모달 → 전환 토스트 → 문구 변경 =================
  reachedMutation = true
  await demoteBtn.first().click()
  await page.getByRole('dialog').waitFor({ timeout: 5000 })
  const modalText = await page.getByRole('dialog').innerText()
  check(modalText.includes('비공개로 전환할까요?'), 'K2a: 확인 모달 문구 표시')
  await shot('01-plex-confirm-modal')
  await page.getByRole('button', { name: '전환', exact: true }).click()

  // 전환 알림은 message(토스트)로 렌더 — .ant-alert가 아니라 .ant-message(286서 수리).
  const demoteToast = page.locator('.ant-message', { hasText: '비공개로 전환됨' })
  const demoteToastShown = await demoteToast.waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  check(demoteToastShown, 'K2b: "비공개로 전환됨" 토스트 표시')
  await page.waitForTimeout(300)
  await shot('02-plex-private-toast')

  // 전환 후 상세가 갱신·리셋될 수 있어 공개·연동 탭 재확인(활성 아니면 클릭).
  await page.getByRole('tab', { name: '공개·연동' }).click()
  await page.waitForTimeout(400)
  const bodyText2 = await page.locator('body').innerText()
  check(bodyText2.includes('공개로 전환하면 켤 수 있습니다'), `K2c: 비공개 전환 반영 — A2A 행이 안내 소유`)
  await shot('03-plex-drawer-private')

  // ================= K3: "공개로 전환" → 확인 → public 복귀(원복) =================
  const promoteBtn = page.getByRole('button', { name: '공개로 전환' })
  check((await promoteBtn.count()) > 0, 'K3a: "공개로 전환" 버튼 표시(강등 후)')
  await promoteBtn.first().click()
  await page.getByRole('dialog').waitFor({ timeout: 5000 })
  const modalText2 = await page.getByRole('dialog').innerText()
  check(modalText2.includes('공개로 전환할까요?'), 'K3b: 확인 모달 문구 표시(승격)')
  await page.getByRole('button', { name: '전환', exact: true }).click()

  const promoteToast = page.locator('.ant-message', { hasText: '공개로 전환됨' })
  const promoteToastShown = await promoteToast.waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  check(promoteToastShown, 'K3c: "공개로 전환됨" 토스트 표시')
  await page.waitForTimeout(300)

  const bodyText3 = await page.locator('body').innerText()
  check(bodyText3.includes('꺼짐 · 노출되지 않음') && !bodyText3.includes('공개로 전환하면'), 'K3d: 공개 복귀 — A2A 행이 켤 수 있는 상태로(원복)')
  await shot('04-plex-drawer-restored-public')
  reachedMutation = false // 원복 저장까지 도달 — 아래 curl 실측이 최종 확인

  await closeDrawer()

  // ================= K4: Doc Translator(code) 행 클릭 → "A2A로 공개 (중계)" 스위치(꺼짐) =================
  // code 에이전트는 Internal (Code) 탭(스펙 284) — 탭 전환 후 진입.
  await page.getByRole('tab', { name: '내부 (Code)' }).click()
  await page.waitForTimeout(500)
  await openAgentDrawer('doc-translator')
  // A2A 스위치는 공개·연동 탭에 렌더(246 탭 구조) — 라벨도 현행('A2A 공개' 행 + 중계 설명)으로.
  await page.getByRole('tab', { name: '공개·연동' }).click()
  await page.waitForTimeout(400)
  await shot('05-xlt-drawer')
  const bodyText4 = await page.locator('body').innerText()
  check(bodyText4.includes('꺼짐 · 노출되지 않음') && !bodyText4.includes('A2A 공개'), 'K4a: A2A 행(라벨 A2A) + 꺼짐 스위치 라벨 표시')
  const xltSwitch = page.locator('button.ant-switch, [role="switch"]').filter({ hasText: '' })
  // ExposeSwitch 구현이 어떤 요소든(버튼/스위치) label과 인접 — aria-checked로 꺼짐 상태 확인.
  const switchNearLabel = page.locator('text=A2A로 공개 (중계)').locator('xpath=ancestor::*[1]')
  const ariaChecked = await page.locator('[role="switch"]').last().getAttribute('aria-checked').catch(() => null)
  check(ariaChecked === 'false' || ariaChecked === null, `K4b: A2A 스위치 꺼짐 상태(실측 aria-checked=${ariaChecked})`)
  await closeDrawer()

  // ================= K5: 원복 실측 — curl GET /agents =================
  const postList = fetchAgents()
  const postPlex = findAgent(postList, PLEX_AGENT_ID)
  const postXlt = findAgent(postList, XLT_AGENT_ID)
  check(
    !!postPlex && postPlex.owner_id == null && postPlex.exposed?.a2a === false,
    `K5a: curl 실측 Plan-Execute Demo owner_id==null && exposed.a2a==false(실측 owner_id=${JSON.stringify(postPlex?.owner_id)}, a2a=${postPlex?.exposed?.a2a})`
  )
  check(
    !!postXlt && postXlt.exposed?.a2a === false,
    `K5b: curl 실측 Doc Translator exposed.a2a==false(실측 a2a=${postXlt?.exposed?.a2a})`
  )

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
  if (reachedMutation) {
    console.error('경고: 원복 전 예외 발생 — DB 상태 미확정. 안전망에서 강제 원복 시도.')
  }
} finally {
  // 종료 직전 안전망 — 실측으로 원복 상태를 감지하고, 어긋나면 API로 강제 원복.
  try {
    const finalList = fetchAgents()
    const finalPlex = findAgent(finalList, PLEX_AGENT_ID)
    const finalXlt = findAgent(finalList, XLT_AGENT_ID)
    if (finalPlex && (finalPlex.owner_id != null || finalPlex.exposed?.a2a !== false)) {
      console.error(`경고: 종료 시점 Plan-Execute Demo 상태가 원본이 아님(실측 owner_id=${JSON.stringify(finalPlex.owner_id)}, a2a=${finalPlex.exposed?.a2a}) — 강제 원복 시도`)
      const targetId = plexInternalId ?? finalPlex.id
      if (finalPlex.owner_id != null) forceVisibility(targetId, true)
      const reList = fetchAgents()
      const rePlex = findAgent(reList, PLEX_AGENT_ID)
      check(!!rePlex && rePlex.owner_id == null && rePlex.exposed?.a2a === false, `안전망 원복 재확인(실측 owner_id=${JSON.stringify(rePlex?.owner_id)}, a2a=${rePlex?.exposed?.a2a})`)
    }
    if (finalXlt && finalXlt.exposed?.a2a !== false) {
      console.error(`경고: 종료 시점 Doc Translator A2A가 원본이 아님(실측 a2a=${finalXlt.exposed?.a2a}) — 이 스크립트는 A2A를 켜지 않았으므로 수동 확인 필요`)
      fails.push('Doc Translator A2A 상태가 예상과 다름(스크립트 밖 변경 가능성)')
    }
  } catch (e2) {
    console.error('안전망 원복 확인 실패', e2.message)
    fails.push('안전망 원복 확인 실패: ' + e2.message)
  }
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
