/* 노드형 편집 폼 정직성 점검 후속(2026-07-10, learning 152 기준).
   ① 새 에이전트(노드형) 1단계: 모델·페르소나 필드 부재(노드 소유 — 기존 보장 회귀).
   ② 2단계(하는 일): 노드에 문서 컬렉션을 넣으면 "최소 유사도" 슬라이더가 즉시 나타나고,
      빼면 사라진다(저장된 풀이 아니라 편집 중 노드에서 실시간 파생).
   ③ 3단계(세부): Temperature 안내에 "모든 노드의 모델에 적용" 명시(pipeline.py:79 소비 사실).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright node tests/browser/verify-pipeline-form-ragscore.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1100 } })).newPage()
const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  const colsRes = await page.request.get(`${URL}/api/collections`)
  const cols = colsRes.ok() ? await colsRes.json() : []
  const colName = cols[0]?.name
  check(!!colName, `사전조건: 컬렉션 존재 (${colName ?? '없음'})`)

  await page.getByRole('menuitem', { name: '에이전트' }).click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(600)
  const form = page.getByRole('dialog')
  await form.getByPlaceholder('예: research-assistant').fill('probe-pf-' + Date.now().toString(36))
  const kind = form.locator('label', { hasText: '에이전트 종류' }).first()
  await kind.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)

  // ── ① 1단계: 모델·페르소나 부재 ──
  check((await form.getByText('페르소나', { exact: true }).count()) === 0, `① 1단계 페르소나 필드 부재(노드 소유)`)
  check((await form.getByText('모델', { exact: true }).count()) === 0, `① 1단계 모델 필드 부재(노드 소유)`)

  // ── ② 2단계: 문서 넣고 빼기 → 슬라이더 실시간 파생 ──
  await form.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await form.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(400)
  check((await form.getByText('최소 유사도', { exact: false }).count()) === 0, `② 문서 없음 → 슬라이더 없음`)
  await form.locator('.ant-select', { has: page.locator('input') }).filter({ hasText: '' }).last()
  const docSelect = form.getByText('문서 (선택)').locator('..').locator('.ant-select').first()
  await docSelect.click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: colName }).first().click()
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  check((await form.getByText('최소 유사도', { exact: false }).count()) > 0, `② 노드에 문서 추가 → 슬라이더 등장(실시간 파생)`)
  check((await form.getByText(colName, { exact: false }).count()) > 0, `② 슬라이더에 컬렉션명 노출`)
  // 제거 → 사라짐
  await docSelect.click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: colName }).first().click()
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  check((await form.getByText('최소 유사도', { exact: false }).count()) === 0, `② 문서 제거 → 슬라이더 소멸`)

  // ── ③ 3단계: Temperature 적용 범위 명시 ──
  const ta = form.locator('textarea').first()
  await ta.fill('p') // 노드 프롬프트(다음 활성 조건)
  await page.waitForTimeout(300)
  await form.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  // Temperature 스위치 켜기 → 안내 문구
  await form.locator('.ant-switch').first().click()
  await page.waitForTimeout(300)
  check((await form.getByText('모든 노드의 모델에 적용', { exact: false }).count()) > 0, `③ Temperature 적용 범위 명시(노드형)`)

  console.log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  console.log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
