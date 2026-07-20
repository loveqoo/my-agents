/* 스펙 419 — 노드형 플레이그라운드 오버라이드 세부 탭에 세션 모델 설정 숨김(시스템 Chrome).
   Playground → 노드형(research-pipeline-demo) 선택 → 오버라이드 → 세부 탭: "모델 설정" 없음·
   단기 기억 있음. 이어 직접형(personal-secretary) → 오버라이드 → 세부: "모델 설정" 있음(무회귀).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         VW=1280 node tests/browser/shot-419-node-override-model.mjs /tmp/shot-419 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/shot-419'
const VW = Number(process.env.VW ?? 1280)
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let fails = 0
const check = (cond, msg) => { log((cond ? 'ok  ' : 'FAIL ') + msg); if (!cond) fails++ }

async function pickAgent(name) {
  // AgentCombo 트리거 = 에이전트 아바타(.ant-avatar)를 담은 상단 버튼(DebugChat.tsx). 사이드바
  // 유저 아바타보다 DOM 앞이라 first(). 열고 드롭다운서 이름 클릭.
  const combo = page.locator('button').filter({ has: page.locator('.ant-avatar') }).first()
  await combo.click().catch(() => {})
  await page.waitForTimeout(700)
  await page.getByText(name, { exact: false }).first().click()
  await page.waitForTimeout(1000)
}

// 오버라이드 열고 세부 탭으로 → {hasModelSetting, hasShortTerm}
async function openOverrideDetail() {
  await page.getByRole('button', { name: '오버라이드' }).first().click()
  await page.waitForTimeout(800)
  // 세부는 Steps 2단계 — 라벨 직접 클릭이 아니라 "다음" 버튼으로 이동(양 유형 동일).
  await page.getByRole('button', { name: '다음' }).first().click()
  await page.waitForTimeout(600)
  const hasModelSetting = await page.getByText(/모델 설정/).count()
  const hasShortTerm = await page.getByText(/단기 기억/).count()
  return { hasModelSetting, hasShortTerm }
}
async function closeOverride() {
  // 열려 있으면 '오버라이드' 토글로 닫는다(적용 안 함). 닫힌 상태 보장 위해 조건부.
  const closeHandle = page.getByRole('button', { name: '오버라이드 닫기' }).first()
  if (await closeHandle.count()) { await closeHandle.click().catch(() => {}) }
  else { await page.getByRole('button', { name: '오버라이드' }).first().click().catch(() => {}) }
  await page.waitForTimeout(600)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)

  // ── 노드형 ──
  await pickAgent('research-pipeline-demo')
  const node = await openOverrideDetail()
  await page.screenshot({ path: `${OUT}-node.png`, fullPage: true })
  log('NODE=' + JSON.stringify(node))
  check(node.hasModelSetting === 0, '노드형 오버라이드 세부: "모델 설정" 없음')
  check(node.hasShortTerm > 0, '노드형 오버라이드 세부: "단기 기억" 있음(유지)')
  await closeOverride()

  // ── 직접형 무회귀 ──
  await pickAgent('personal-secretary')
  const direct = await openOverrideDetail()
  await page.screenshot({ path: `${OUT}-direct.png`, fullPage: true })
  log('DIRECT=' + JSON.stringify(direct))
  check(direct.hasModelSetting > 0, '직접형 오버라이드 세부: "모델 설정" 있음(무회귀)')

  log(fails === 0 ? 'SHOT419_OK' : `SHOT419_FAIL(${fails})`)
  process.exitCode = fails === 0 ? 0 : 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
