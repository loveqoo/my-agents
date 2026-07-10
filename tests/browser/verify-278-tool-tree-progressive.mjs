/* 도구 트리 점진 공개 검증 (스펙 278) — 필수 단언(UI 기능적).
   ① 초기: 도구 아코디언 접힘(선택 없음) — 트리 미노출. ② 아코디언 열면 서버만(1 depth) — 리프 미노출.
   ③ 스위처(블릿) 클릭 → 리프 노출, 재클릭 → 접힘(동작 수리). ④ 리프에 도구 설명 노출(toolsMeta).
   ⑤ 검색 → 매칭 서버 자동 확장(리프 노출). ⑥ 리프 체크→값 반영(277 기능 무회귀).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-278-tool-tree-progressive.mjs */
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

  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill('pg278-' + Date.now().toString(36))
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(600)
  const modal = page.locator('.ant-modal:visible').last()

  // ① 초기: 아코디언 접힘 — 트리 미노출(서버 노드도 안 보임)
  const treeVisible0 = await modal.locator('.ant-tree').isVisible().catch(() => false)
  check(!treeVisible0, `① 초기 아코디언 접힘 — 트리 미노출 (visible=${treeVisible0})`)

  // ② 아코디언 열기 → 서버만(1 depth)
  const toolHeader = modal.locator('.ant-collapse-header').filter({ hasText: '도구' }).filter({ hasNotText: '승인' }).first()
  await toolHeader.click()
  await page.waitForTimeout(400)
  const tree = modal.locator('.ant-tree').first()
  const serverNode = tree.locator('.ant-tree-treenode', { has: page.getByText('calc-tools', { exact: true }) }).first()
  check(await serverNode.count() > 0, `② 서버 노드 노출(calc-tools)`)
  const leafBefore = await tree.getByText('multiply', { exact: true }).isVisible().catch(() => false)
  check(!leafBefore, `② 1 depth — 리프(multiply) 미노출 (visible=${leafBefore})`)

  // ③ 스위처(블릿) → 리프 노출 → 재클릭 접힘
  await serverNode.locator('.ant-tree-switcher').first().click()
  await page.waitForTimeout(400)
  const leafAfter = await tree.getByText('multiply', { exact: true }).isVisible().catch(() => false)
  check(leafAfter, `③ 스위처 클릭 → 리프 노출 (visible=${leafAfter})`)
  await serverNode.locator('.ant-tree-switcher').first().click()
  await page.waitForTimeout(400)
  const leafCollapsed = await tree.getByText('multiply', { exact: true }).isVisible().catch(() => false)
  check(!leafCollapsed, `③ 재클릭 → 접힘 (visible=${leafCollapsed})`)

  // ④ 리프 설명 노출 — local-tools 확장 후 설명 텍스트(웹 검색 mock 설명 등) 존재
  const localNode = tree.locator('.ant-tree-treenode', { has: page.getByText('local-tools', { exact: true }) }).first()
  await localNode.locator('.ant-tree-switcher').first().click()
  await page.waitForTimeout(400)
  const treeText = await tree.innerText()
  // toolsMeta description이 리프 아래 뮤트 줄로 — 도구명 외 설명 문구가 트리 텍스트에 있어야
  const hasDesc = /검색|삭제|되돌려|echo|mock|record/i.test(treeText.replace(/web_search|delete_record|echo/g, ''))
  check(hasDesc, `④ 리프에 도구 설명 노출 (treeText 일부: ${JSON.stringify(treeText.slice(0, 120))})`)

  // ⑤ 검색 → 매칭 서버 자동 확장
  await modal.getByPlaceholder('도구 검색... (이름·설명)').fill('multiply')
  await page.waitForTimeout(400)
  const searchLeaf = await tree.getByText('multiply', { exact: true }).isVisible().catch(() => false)
  check(searchLeaf, `⑤ 검색 시 매칭 서버 자동 확장(multiply 노출)`)
  await modal.getByPlaceholder('도구 검색... (이름·설명)').fill('')
  await page.waitForTimeout(300)

  // ⑥ 리프 체크 → 배지 반영(277 기능 무회귀)
  const calcNode2 = tree.locator('.ant-tree-treenode', { has: page.getByText('calc-tools', { exact: true }) }).first()
  await calcNode2.locator('.ant-tree-switcher').first().click()
  await page.waitForTimeout(300)
  const addNode = tree.locator('.ant-tree-treenode', { has: page.getByText('add', { exact: true }) }).first()
  await addNode.locator('.ant-tree-checkbox').first().click()
  await page.waitForTimeout(300)
  const badge = await modal.locator('.ant-collapse-header .ant-tag', { hasText: /^1\s*\/\s*\d+$/ }).count()
  check(badge > 0, `⑥ 리프 체크 → 배지 1/N 반영 (found ${badge})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
