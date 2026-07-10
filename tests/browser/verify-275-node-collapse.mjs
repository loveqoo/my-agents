/* 노드 카드 접기/펼치기 검증 (스펙 275) — 필수 단언(UI 기능적).
   ① 노드 추가 → 펼침(본문 컨트롤 노출). ② 접기 → 본문 숨김+요약 헤더(이름·모델·프롬프트 앞부분).
   ③ 미완성 노드 접힘 헤더에 "작성 필요". ④ 펼친 상태서 이름 Input 클릭이 접힘 안 토글(123 회귀).
   ⑤ 다시 펼치면 본문 복원·값 유지. ⑥ 둘째 노드 추가 → 새 노드만 펼침·기존 접힘 유지.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-275-node-collapse.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1200 } })).newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 노드형 폼 → 노드 추가
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const typeField = page.locator('label', { hasText: '에이전트 종류' }).first()
  await typeField.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
  await page.getByPlaceholder('예: research-assistant').fill('col-275-' + Date.now().toString(36))
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(500)

  const modal = page.locator('.ant-modal:visible').last()
  // 노드 카드 Collapse만(카드 안 도구 아코디언(278)이 중첩되므로 collapsible="icon" 헤더 보유로 구분)
  const col = (idx) => modal.locator('.ant-collapse', { has: page.locator('.ant-collapse-collapsible-icon') }).nth(idx)

  // ① 추가 직후 펼침 — 본문 컨트롤(프롬프트 TextArea) 노출
  const bodyVisible1 = await col(0).locator('textarea').isVisible()
  check(bodyVisible1, '① 노드 추가 직후 펼침(프롬프트 TextArea 노출)')

  // 이름·프롬프트 작성 (④ 이름 Input 클릭이 접힘 안 토글 확인 겸)
  const nameInput = col(0).locator('.ant-collapse-header input').first()
  await nameInput.click()
  await page.waitForTimeout(200)
  check(await col(0).locator('textarea').isVisible(), '④ 이름 Input 클릭해도 펼침 유지(123 회귀)')
  await nameInput.fill('분석')
  await col(0).locator('textarea').first().fill('입력을 분석해 핵심 3가지를 뽑아라')
  await page.waitForTimeout(200)

  // ② 접기 — 아이콘 클릭 → 본문 숨김 + 요약 헤더
  await col(0).locator('.ant-collapse-expand-icon').first().click()
  await page.waitForTimeout(400)
  const bodyGone = await col(0).locator('textarea').isVisible().catch(() => false)
  check(!bodyGone, '② 접힘 — 본문 숨김')
  const header = await col(0).locator('.ant-collapse-header').first().innerText() // 중첩 도구 아코디언(278) 제외
  check(header.includes('분석'), `② 접힘 헤더에 이름 (got ${JSON.stringify(header.slice(0, 80))})`)
  check(/mock-llm|qwen/.test(header), '② 접힘 헤더 요약에 모델')
  check(header.includes('입력을 분석해'), '② 접힘 헤더 요약에 프롬프트 앞부분')
  check(!header.includes('작성 필요'), '② 완성 노드엔 "작성 필요" 없음')

  // ⑥ 둘째 노드 추가 → 새 노드만 펼침, 첫 노드 접힘 유지
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(400)
  check(!(await col(0).locator('textarea').isVisible().catch(() => false)), '⑥ 기존 노드 접힘 유지')
  check(await col(1).locator('textarea').isVisible(), '⑥ 새 노드는 펼침')

  // ③ 미완성(프롬프트 빈) 둘째 노드 접기 → "작성 필요"
  await col(1).locator('.ant-collapse-expand-icon').first().click()
  await page.waitForTimeout(400)
  const header2 = await col(1).locator('.ant-collapse-header').first().innerText() // 중첩 도구 아코디언(278) 제외
  check(header2.includes('작성 필요'), `③ 미완성 노드 접힘 헤더에 "작성 필요" (got ${JSON.stringify(header2.slice(0, 60))})`)

  // ⑤ 다시 펼치면 본문 복원·값 유지
  await col(0).locator('.ant-collapse-expand-icon').first().click()
  await page.waitForTimeout(400)
  const promptVal = await col(0).locator('textarea').first().inputValue()
  check(promptVal === '입력을 분석해 핵심 3가지를 뽑아라', `⑤ 펼침 복원·값 유지 (got ${JSON.stringify(promptVal)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
