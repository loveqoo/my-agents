/* 스펙 080 검증 — Playground 미반영 초안 배지 stale 해소(이벤트 전파 + 포커스 백스톱).
   배경: Playground는 마운트 1회만 listAgents() → 다른 탭/뷰의 활성화를 모른 채 스냅샷을 들고
   '미반영 초안' 배지(스펙 078)가 stale하게 남는다(사용자 보고). 080은 (1) BroadcastChannel로
   변경을 다른 탭에 즉시 전파, (2) 포커스/가시성 재페치 백스톱으로 정합한다.

   시나리오:
   PART1 (백스톱, 단일 페이지) — API로 draft 생성→TARGET 선택→배지=1 →API activate(서버 draft 0)
     →배지 여전히 1(STALE 재현) →window 'focus' 디스패치→재페치→배지=0(백스톱 수정 동작).
   PART2 (BroadcastChannel, 두 페이지/같은 컨텍스트) — draft 재생성→pageA focus로 배지=1 셋업
     →pageB(다른 JS 컨텍스트)에서 API activate + BroadcastChannel('agents') post(=다른 탭의 변경
     대역) →pageA는 포커스 없이도 배지=0(순수 이벤트 전파). BroadcastChannel은 같은 채널 객체엔
     자신이 post한 걸 안 주므로 반드시 별도 페이지에서 쏴야 전달된다(=실제 탭 분리 모사).
   PART3 (무회귀) — 활성만인 에이전트 선택 시 배지=0, draft 있는 에이전트 선택 시 배지=1 유지.

   셀렉터 0개 = 측정 실패(learning 080) → 명시적으로 실패 처리.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-draft-staleness-080.mjs /tmp/stale080 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/stale080'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const TARGET = process.env.TARGET ?? 'Personal Secretary'
const DEFAULT_AGENT = process.env.DEFAULT_AGENT ?? 'Doc Translator' // list[0] = 콤보 기본 트리거

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let failed = false
const must = (cond, msg) => { if (!cond) { failed = true; log('FAIL ' + msg) } else log('OK ' + msg) }

const badge = (p) => p.locator('.ant-tag', { hasText: '미반영 초안' }).count()

// 페이지 컨텍스트에서 API 호출(쿠키 재사용). 서버 진실원 = draft 버전 배열.
const serverDrafts = (p, nm) => p.evaluate(async (name) => {
  const l = await (await fetch('/api/agents', { credentials: 'include' })).json()
  const a = l.find((x) => x.name === name)
  return a ? (a.versions || []).filter((v) => v.status === 'draft').map((v) => v.version) : null
}, nm)

const makeDraft = (p, nm) => p.evaluate(async (name) => {
  const l = await (await fetch('/api/agents', { credentials: 'include' })).json()
  const a = l.find((x) => x.name === name)
  const active = (a.versions || []).find((v) => v.status === 'active')
  const r = await fetch('/api/agents/' + a.id, {
    method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: a.name, config: active.config }),
  })
  return r.status
}, nm)

// activate + (선택) BroadcastChannel 신호. broadcast=true면 onAgentsChanged 수신자에게 전파.
const activate = (p, nm, broadcast) => p.evaluate(async ({ name, bc }) => {
  const l = await (await fetch('/api/agents', { credentials: 'include' })).json()
  const a = l.find((x) => x.name === name)
  const d = (a.versions || []).find((v) => v.status === 'draft')
  const r = await fetch('/api/agents/' + a.id + '/activate', {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: d.version }),
  })
  if (bc && typeof BroadcastChannel !== 'undefined') new BroadcastChannel('agents').postMessage('changed')
  return r.status
}, { name: nm, bc: !!broadcast })

const login = async (p) => {
  await p.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await p.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await p.getByPlaceholder('you@example.com').fill(EMAIL)
  await p.getByPlaceholder('비밀번호').fill(PASSWORD)
  await p.getByRole('button', { name: '로그인' }).click()
  await p.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await p.waitForTimeout(500)
}

const gotoPlayground = async (p) => {
  await p.getByText('Playground', { exact: true }).first().click()
  await p.waitForTimeout(1400)
}

// 콤보 열고 name 선택. 현재 트리거 라벨(current)을 클릭해 열고 옵션 클릭.
const selectAgent = async (p, name, current) => {
  await p.locator('button', { hasText: current }).first().click().catch(() => {})
  await p.waitForTimeout(400)
  const opt = p.locator('button', { hasText: name }).first()
  must((await opt.count()) > 0, `combo option '${name}' present (0=측정실패)`)
  if (await opt.count()) await opt.click()
  await p.waitForTimeout(800)
}

const fireFocus = (p) => p.evaluate(() => window.dispatchEvent(new Event('focus')))

try {
  await login(page)

  // ===== PART1 — 백스톱(단일 페이지) =====
  const s1 = await makeDraft(page, TARGET)
  log('PART1 makeDraft status=' + s1, 'drafts=' + JSON.stringify(await serverDrafts(page, TARGET)))
  await gotoPlayground(page)
  await selectAgent(page, TARGET, DEFAULT_AGENT)
  const b1 = await badge(page)
  must(b1 >= 1, `PART1 select draft agent → badge=1 (got ${b1})`)
  await page.screenshot({ path: `${OUT}-1a-badge-on.png`, fullPage: true })

  const a1 = await activate(page, TARGET, false) // activate만, 신호 없음 → stale 재현
  await page.waitForTimeout(700)
  log('PART1 activate status=' + a1, 'server drafts=' + JSON.stringify(await serverDrafts(page, TARGET)))
  const bStale = await badge(page)
  must(bStale >= 1, `PART1 STALE 재현: 신호 없이 배지 여전히 1 (got ${bStale}) — 버그 조건 확인`)

  await fireFocus(page) // 백스톱: 포커스 → 재페치
  await page.waitForTimeout(900)
  const bAfterFocus = await badge(page)
  must(bAfterFocus === 0, `PART1 포커스 백스톱 → 배지=0 (got ${bAfterFocus})`)
  await page.screenshot({ path: `${OUT}-1b-after-focus.png`, fullPage: true })

  // ===== PART2 — BroadcastChannel(두 페이지, 같은 컨텍스트) =====
  const s2 = await makeDraft(page, TARGET)
  log('PART2 makeDraft status=' + s2, 'drafts=' + JSON.stringify(await serverDrafts(page, TARGET)))
  await fireFocus(page) // pageA 배지 재점등 셋업(draft 다시 보이게)
  await page.waitForTimeout(900)
  const b2setup = await badge(page)
  must(b2setup >= 1, `PART2 setup: draft 재생성 후 배지=1 (got ${b2setup})`)

  // pageB = 다른 JS 컨텍스트(=다른 탭 대역). 여기서 activate + BroadcastChannel post.
  const pageB = await ctx.newPage()
  await pageB.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await pageB.waitForTimeout(400)
  const a2 = await activate(pageB, TARGET, true) // 서버 draft 0 + 'agents' 채널 신호
  log('PART2 pageB activate status=' + a2, 'server drafts=' + JSON.stringify(await serverDrafts(pageB, TARGET)))
  // pageA에 포커스/가시성 이벤트를 주지 않는다 → 배지가 0이면 순수 BroadcastChannel 전파.
  await page.waitForTimeout(1200)
  const b2 = await badge(page)
  must(b2 === 0, `PART2 BroadcastChannel 전파(포커스 없음) → pageA 배지=0 (got ${b2})`)
  await page.screenshot({ path: `${OUT}-2-broadcast.png`, fullPage: true })
  await pageB.close()

  // ===== PART3 — 무회귀 =====
  // 활성만인 에이전트(DEFAULT_AGENT=code, active) → 배지 0.
  await selectAgent(page, DEFAULT_AGENT, TARGET)
  const bNeg = await badge(page)
  must(bNeg === 0, `PART3 활성만 에이전트 → 배지=0 (got ${bNeg})`)

  // draft 만들고 그 에이전트 선택 → 배지 1(정상 점등 무회귀).
  const s3 = await makeDraft(page, TARGET)
  log('PART3 makeDraft status=' + s3, 'drafts=' + JSON.stringify(await serverDrafts(page, TARGET)))
  await selectAgent(page, TARGET, DEFAULT_AGENT)
  await fireFocus(page) // 방금 만든 draft 반영
  await page.waitForTimeout(900)
  const bPos = await badge(page)
  must(bPos >= 1, `PART3 draft 에이전트 → 배지=1 (got ${bPos})`)
  await page.screenshot({ path: `${OUT}-3-regression.png`, fullPage: true })

  // 정리: TARGET draft activate해 깨끗이.
  await activate(page, TARGET, false)
  log('CLEANUP activate, final drafts=' + JSON.stringify(await serverDrafts(page, TARGET)))

  log(failed ? 'RESULT=FAIL' : 'RESULT=PASS')
  if (failed) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
