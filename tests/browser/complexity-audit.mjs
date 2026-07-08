/* 화면 복잡도 전수 진단(스펙 245 P2) — "어렵다"를 수치로. 전 메뉴를 데스크톱(1280px)으로 순회하며
   ①본문 스크롤 높이 ②최상위 블록 수(본문 직계 구획) ③컨트롤 수(버튼·입력·셀렉트·스위치) 실측.
   순위표가 다음 개편 우선순위의 근거(.dev/backlog 기록용). 판정 없이 측정만(트리아지는 사람이).

   실행: PLAYWRIGHT_DIR=<dir> ADMIN_EMAIL=.. ADMIN_PASSWORD=.. node tests/browser/complexity-audit.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const SCREENS = [
  ['overview', '개요'], ['agents', '에이전트'], ['blocks', '빌딩 블록'],
  ['models', '프로바이더·모델'], ['collections', 'RAG 컬렉션'], ['sessions', '세션'],
  ['memory', '메모리'], ['approvals', '승인'], ['users', '유저'], ['batch', '배치'],
  ['eval', '평가'], ['allowed-hosts', '허용 호스트'], ['settings', '설정'], ['debug', 'Playground'],
]

const MEASURE = () => {
  // 본문 = antd Layout content(사이드바 제외). 폴백 #root.
  const main = document.querySelector('main, .ant-layout-content') ?? document.querySelector('#root')
  const blocks = main
    ? Array.from(main.querySelectorAll(
        '.ant-card, .ant-table-wrapper, .ant-descriptions, .ant-collapse, .ant-alert, .ant-tabs, section, [class*="Panel"]'
      )).filter((el) => el.getBoundingClientRect().height > 24).length
    : 0
  const controls = main
    ? main.querySelectorAll('button, input, textarea, .ant-select, [role="switch"]').length
    : 0
  return {
    scrollH: main ? main.scrollHeight : document.documentElement.scrollHeight,
    viewH: window.innerHeight,
    blocks,
    controls,
  }
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
await page.getByPlaceholder('you@example.com').fill(EMAIL)
await page.getByPlaceholder('비밀번호').fill(PASSWORD)
await page.getByRole('button', { name: '로그인' }).click()
await page.waitForTimeout(1800)

const rows = []
for (const [key, label] of SCREENS) {
  try {
    // 관리자 그룹 하위 메뉴는 그룹을 먼저 펼친다(접혀 있으면 항목이 DOM에 없음).
    let item = page.locator(`[data-menu-id$="${key}"]`).first()
    if (!(await item.count())) {
      const admin = page.getByText('관리자', { exact: true }).first()
      if (await admin.count()) { await admin.click({ timeout: 2000 }).catch(() => {}); await page.waitForTimeout(300) }
      const tools = page.getByText('도구', { exact: true }).first()
      if (await tools.count()) { await tools.click({ timeout: 2000 }).catch(() => {}); await page.waitForTimeout(300) }
      item = page.locator(`[data-menu-id$="${key}"]`).first()
    }
    if (await item.count()) await item.click({ timeout: 4000 })
    else await page.getByText(label, { exact: true }).first().click({ timeout: 4000 })
    await page.waitForTimeout(1200)
    const m = await page.evaluate(MEASURE)
    rows.push({ key, label, ...m, screens: +(m.scrollH / m.viewH).toFixed(1) })
  } catch (e) {
    rows.push({ key, label, error: String(e).slice(0, 60) })
  }
}
await browser.close()

rows.sort((a, b) => (b.blocks ?? 0) + (b.controls ?? 0) / 10 - ((a.blocks ?? 0) + (a.controls ?? 0) / 10))
console.log('화면 | 블록 | 컨트롤 | 세로(화면 배수)')
for (const r of rows) {
  if (r.error) console.log(`${r.label}: 측정 실패(${r.error})`)
  else console.log(`${r.label} | ${r.blocks} | ${r.controls} | ${r.screens}x`)
}
const fs = await import('fs')
fs.mkdirSync('tests/browser/out-complexity', { recursive: true })
fs.writeFileSync('tests/browser/out-complexity/scorecard.json', JSON.stringify(rows, null, 2))
console.log('\nscorecard → tests/browser/out-complexity/scorecard.json')
