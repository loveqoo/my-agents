/* 스펙 109 검증 — 등록 폼 3단계(기본/하는 일/세부설정 접힘) + 하는 일 그룹이 종류로 갈림 + 세부설정 접힘.
   시스템 Chrome. 실행: ADMIN_URL=http://localhost:5173 PLAYWRIGHT_DIR=<abs> node tests/browser/shot-caps-impl-109.mjs /tmp/caps-109 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://localhost:5173'
const OUT = process.argv[2] ?? '/tmp/caps-109'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1200 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
let fails = 0
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails++ }
const mtext = async () => page.locator('.ant-modal-container').innerText()

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(800)
  const modal = page.locator('.ant-modal-container')

  // 1) 3단계 구획 머리말.
  const t1 = await mtext()
  check(t1.includes('기본'), 'H1 구획 "기본"')
  check(t1.includes('이 에이전트가 하는 일'), 'H1 구획 "이 에이전트가 하는 일"')
  check(t1.includes('세부 설정 (선택)'), 'H1 구획 "세부 설정 (선택)"')

  // 2) 세부 설정 기본 접힘 → Temperature 안 보임.
  check(!t1.includes('Temperature'), 'H2 세부설정 기본 접힘(Temperature 숨김)')

  // 3) 직접 응답(기본) → 하는 일 그룹 = 도구/문서/기억/권한, 위임 kind 없음.
  await modal.getByText('이 에이전트가 하는 일', { exact: true }).scrollIntoViewIfNeeded()
  const heads1 = await modal.locator('.ant-collapse-header').allInnerTexts()
  const set1 = heads1.join(' | ')
  check(/도구/.test(set1) && /문서/.test(set1) && /기억/.test(set1) && /권한/.test(set1),
    `H3 직접 응답 그룹=도구·문서·기억·권한 (=${set1})`)
  check(!/다른 에이전트/.test(set1), 'H3 직접 응답엔 "다른 에이전트" 없음')

  // 4) 조율형 → 하는 일 그룹 = 다른 에이전트/도구/문서/사용자 기억.
  const typeSelect = page.getByText('에이전트 종류', { exact: true })
    .locator('xpath=following-sibling::*[contains(@class,"ant-select")][1]')
  await typeSelect.click(); await page.waitForTimeout(300)
  await page.getByText('조율형', { exact: true }).click(); await page.waitForTimeout(400)
  await modal.getByText('이 에이전트가 하는 일', { exact: true }).scrollIntoViewIfNeeded()
  const heads2 = (await modal.locator('.ant-collapse-header').allInnerTexts()).join(' | ')
  check(/다른 에이전트/.test(heads2) && /사용자 기억/.test(heads2),
    `H4 조율형 그룹=다른 에이전트·…·사용자 기억 (=${heads2})`)
  check(!/권한/.test(heads2), 'H4 조율형엔 "권한" 없음(직접 자원 숨김)')

  // 5) 세부 설정 펼치면 Temperature 노출.
  await modal.locator('.ant-collapse-header', { hasText: '세부 설정' }).click()
  await page.waitForTimeout(300)
  check((await mtext()).includes('Temperature'), 'H5 세부설정 펼침 → Temperature 노출')

  // 6) 직접 응답으로 돌려 "기억" 그룹 펼쳐 토글 → 카운트 반영.
  await typeSelect.click(); await page.waitForTimeout(300)
  await page.getByText('직접 응답', { exact: true }).click(); await page.waitForTimeout(400)
  await modal.getByText('이 에이전트가 하는 일', { exact: true }).scrollIntoViewIfNeeded()
  const memHead = modal.locator('.ant-collapse-header').filter({ hasText: '기억' }).first()
  await memHead.click(); await page.waitForTimeout(300)
  const memBox = modal.locator('label.ant-checkbox-wrapper', { hasText: '단기' }).first()
  if (await memBox.count()) {
    await memBox.locator('input').check(); await page.waitForTimeout(250)
    const tagTxt = await modal.locator('.ant-collapse-header').filter({ hasText: '기억' }).locator('.ant-tag').first().innerText()
    check(/1\//.test(tagTxt), `H6 기억 토글 → 헤더 카운트 1/N (=${tagTxt})`)
  } else {
    log('  --  H6 스킵(메모리 블록 없음)')
  }

  await page.screenshot({ path: `${OUT}.png`, fullPage: true })
  log('SHOT ' + OUT + '.png')
  log(fails === 0 ? 'VERIFY109_OK' : `VERIFY109_FAIL(${fails})`)
  if (fails) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
