/* 일회용 survey(스펙 #6) — admin 전 뷰의 가로 overflow를 수치로 잰다(추측 금지).
   각 뷰로 이동 후: (a) document 가로 스크롤(docScroll = documentElement.scrollWidth - clientWidth),
   (b) 모든 table의 scrollWidth - wrapClientW 중 최대, (c) 뷰포트 밖으로 넘친 요소 상위 몇 개.
   실행 환경은 measure-collections-table.mjs와 동일(login → 메뉴 클릭 → 측정).
   VW로 뷰포트 폭 주입(기본 1280·좁은 케이스 1024도 재실행). */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const VW = Number(process.env.VW ?? 1280)
const SHOT_DIR = process.env.SHOT_DIR ?? '/tmp'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 960 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

// 최상위 메뉴(항상 보임) + 관리자 서브메뉴(펼쳐야 보임)
const TOP = ['개요', '에이전트', '빌딩 블록', '프로바이더·모델', 'RAG 컬렉션', '세션', '메모리']
const ADMIN = ['유저', '배치', '허용 호스트']

async function measure() {
  return await page.evaluate((vw) => {
    const docScroll = document.documentElement.scrollWidth - document.documentElement.clientWidth
    let worstTable = 0
    const tables = [...document.querySelectorAll('table')]
    for (const t of tables) {
      const wrap = t.parentElement
      const o = t.scrollWidth - (wrap?.clientWidth ?? t.clientWidth)
      if (o > worstTable) worstTable = o
    }
    // 뷰포트 오른쪽 경계를 넘는 요소(leaf 위주) 상위 5
    const over = []
    for (const el of document.querySelectorAll('*')) {
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.right > vw + 1 && el.children.length <= 2) {
        over.push({ tag: el.tagName.toLowerCase(), cls: (el.className || '').toString().slice(0, 40), right: Math.round(r.right) })
      }
    }
    over.sort((a, b) => b.right - a.right)
    return { docScroll, worstTable, tableCount: tables.length, over: over.slice(0, 5) }
  }, VW)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  log('VIEWPORT=' + VW)
  const results = []
  for (const label of TOP) {
    await page.getByText(label, { exact: true }).first().click().catch(() => {})
    await page.waitForTimeout(1000)
    const m = await measure()
    results.push({ label, ...m })
    log(`[${label}] doc=${m.docScroll} worstTable=${m.worstTable} tables=${m.tableCount}` +
      (m.over.length ? ' OVER=' + JSON.stringify(m.over) : ''))
    if (m.docScroll > 0 || m.worstTable > 0) {
      await page.screenshot({ path: `${SHOT_DIR}/overflow-${VW}-${label.replace(/[^\w가-힣]/g, '')}.png`, fullPage: false })
    }
  }
  // 관리자 서브메뉴 펼치기
  await page.getByText('관리자', { exact: true }).first().click().catch(() => {})
  await page.waitForTimeout(500)
  for (const label of ADMIN) {
    await page.getByText(label, { exact: true }).first().click().catch(() => {})
    await page.waitForTimeout(1000)
    const m = await measure()
    results.push({ label, ...m })
    log(`[${label}] doc=${m.docScroll} worstTable=${m.worstTable} tables=${m.tableCount}` +
      (m.over.length ? ' OVER=' + JSON.stringify(m.over) : ''))
    if (m.docScroll > 0 || m.worstTable > 0) {
      await page.screenshot({ path: `${SHOT_DIR}/overflow-${VW}-${label.replace(/[^\w가-힣]/g, '')}.png`, fullPage: false })
    }
  }
  const bad = results.filter((r) => r.docScroll > 0 || r.worstTable > 0)
  log('SUMMARY bad=' + bad.length + '/' + results.length + ' => ' + JSON.stringify(bad.map((b) => `${b.label}(doc=${b.docScroll},tbl=${b.worstTable})`)))
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}
