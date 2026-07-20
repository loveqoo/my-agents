/* 스펙 417 — 노드형 세부 탭에서 "모델 설정 오버라이드" 숨김 검증(시스템 Chrome).
   admin(vite :5173) 로그인 → suite-pipeline(노드형) 편집 → 세부 스텝: "모델 설정 오버라이드" 없음·
   "단기 기억" 있음. 이어 직접형 편집 → 세부: "모델 설정 오버라이드" 있음(무회귀).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         VW=1280 node tests/browser/shot-417-node-model-params.mjs /tmp/shot-417 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/shot-417'
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

// 이름으로 행 편집 열기 → 세부 스텝 점프 → "모델 설정 오버라이드"/"단기 기억" 존재 반환.
// 행 액션 버튼 = [편집(연필), 삭제(휴지통)] — **first()=편집**. 삭제(last)는 절대 클릭 금지.
async function openDetailFor(name) {
  const row = page.getByRole('row', { name: new RegExp(name) }).first()
  await row.getByRole('button').first().click()  // 편집(연필) — 삭제 아님
  await page.waitForTimeout(800)
  // 위저드 세부 스텝(edit=자유 이동). Steps 항목 '세부' 클릭.
  await page.getByText('세부', { exact: true }).first().click()
  await page.waitForTimeout(500)
  const hasOverride = await page.getByText('모델 설정 오버라이드', { exact: true }).count()
  const hasShortTerm = await page.getByText(/단기 기억/).count()
  return { hasOverride, hasShortTerm }
}

async function closeForm() {
  // '취소'로 닫는다(저장 안 함 — 무변경 보장). 확인 다이얼로그 뜨면 '취소'가 여럿일 수 있어 last.
  const cancel = page.getByRole('button', { name: '취소' }).last()
  if (await cancel.count()) { await cancel.click(); await page.waitForTimeout(500) }
  // 취소는 그 에이전트 상세 드로워로 복귀 — '에이전트 목록' 브레드크럼으로 전체 목록 복귀.
  const back = page.getByText('에이전트 목록', { exact: true }).first()
  if (await back.count()) { await back.click(); await page.waitForTimeout(700) }
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // ── 노드형(research-pipeline-demo) ──
  const node = await openDetailFor('research-pipeline-demo')
  await page.screenshot({ path: `${OUT}-node-detail.png`, fullPage: true })
  log('NODE_DETAIL=' + JSON.stringify(node))
  check(node.hasOverride === 0, '노드형 세부: "모델 설정 오버라이드" 없음')
  check(node.hasShortTerm > 0, '노드형 세부: "단기 기억"은 있음(모델 독립 — 유지)')
  await closeForm()

  // ── 직접형(personal-secretary) 무회귀 ──
  const direct = await openDetailFor('personal-secretary')
  await page.screenshot({ path: `${OUT}-direct-detail.png`, fullPage: true })
  log('DIRECT_DETAIL=' + JSON.stringify(direct))
  check(direct.hasOverride > 0, '직접형 세부: "모델 설정 오버라이드" 있음(무회귀)')
  await closeForm()

  log(fails === 0 ? 'SHOT417_OK' : `SHOT417_FAIL(${fails})`)
  process.exitCode = fails === 0 ? 0 : 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
