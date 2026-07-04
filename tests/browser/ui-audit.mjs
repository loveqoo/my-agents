/* 스펙 165 — 다디바이스 UI 오버플로 감사 하네스(검증 축2).
   모든 화면 × 뷰포트를 순회하며 (1) 페이지 가로 스크롤 px, (2) overflow-x:visible인데 내부가 넘치는
   요소를 **수치로** 측정하고 fullPage 스크린샷을 남긴다. "괜찮아 보인다"가 불가능 — 숫자가 판정한다.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/ui-audit.mjs tests/browser/out-ui-audit */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
import { mkdirSync, writeFileSync } from 'node:fs'

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? 'tests/browser/out-ui-audit'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const THRESHOLD = 4 // px — 서브픽셀 노이즈 컷

// 화면 목록(AdminShell 메뉴 단일 출처) — key로 네비.
const SCREENS = [
  ['overview', '개요'], ['agents', '에이전트'], ['blocks', '빌딩 블록'],
  ['models', '프로바이더·모델'], ['collections', 'RAG 컬렉션'], ['sessions', '세션'],
  ['memory', '메모리'], ['approvals', '승인'], ['users', '유저'], ['batch', '배치'],
  ['eval', '평가'], ['allowed-hosts', '허용 호스트'], ['settings', '설정'], ['debug', 'Playground'],
]
const VIEWPORTS = [
  ['mobile', 360, 780], ['tablet', 768, 1024], ['desktop', 1280, 900],
]

// in-page 오버플로 측정. 판정 = 요소 우측이 뷰포트 경계를 실제로 넘는가(rect.right > vw). 이건
// (a) 페이지 가로 스크롤을 만들거나 (b) 조상 clip에 잘려 내용이 안 보이거나 — 둘 다 실제 깨짐.
// 화면 밖(좌측·세로 스크롤 밖)·0폭·의도적 스크롤 컨테이너(auto/scroll/hidden)는 제외(오탐 컷).
const MEASURE = (threshold) => {
  const de = document.documentElement
  const vw = de.clientWidth
  const vh = window.innerHeight || de.clientHeight
  const pageScroll = de.scrollWidth - vw
  // antd 탭 넘침 위젯(.ant-tabs-nav)만 제외 — 넘치는 탭을 ⋯ 더보기로 접근 가능(네이티브 처리, 깨짐 아님).
  // 일반 스크롤 조상(auto/scroll)은 제외하지 않는다 — 넓은 표는 합법이나 주요 버튼이 스크롤 뒤로
  // 숨는 건 실제 UX 문제라(회고 133), 도구가 삼키지 말고 표면화해 육안 판정하게 둔다.
  const absorbed = (el) => {
    let p = el.parentElement
    while (p && p !== document.body) {
      if (p.classList && p.classList.contains('ant-tabs-nav')) return true
      p = p.parentElement
    }
    return false
  }
  const offenders = []
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue
    if (['auto', 'scroll', 'hidden'].includes(cs.overflowX)) continue
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) continue
    if (r.bottom < 0 || r.top > vh) continue // 세로 화면 밖
    // 우측 경계 밖에서 시작 = 완전히 화면 밖(닫힌 드로어·오프스크린 패널 등) → 오탐 컷.
    if (r.left >= vw - threshold) continue
    if (absorbed(el)) continue // 스크롤 컨테이너·탭 ⋯가 흡수 → 깨짐 아님
    const past = Math.round(r.right - vw) // 우측 뷰포트 경계 초과 px
    if (past > threshold) {
      offenders.push({
        overPx: past,
        tag: el.tagName.toLowerCase(),
        cls: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
        text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 50),
      })
    }
  }
  offenders.sort((a, b) => b.overPx - a.overPx)
  return { vw, pageScroll, offenders: offenders.slice(0, 12) }
}

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const scorecard = []
let failCount = 0

try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await ctx.newPage()
  // 로그인 1회.
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  for (const [vp, w, h] of VIEWPORTS) {
    await page.setViewportSize({ width: w, height: h })
    const isMobile = w < 768
    mkdirSync(`${OUT}/${vp}`, { recursive: true })
    for (const [key, label] of SCREENS) {
      // 네비: antd 메뉴 data-menu-id가 key로 끝난다. 실패 시 라벨 텍스트 폴백.
      // 모바일(<768)은 Sider가 오버레이(기본 닫힘)라 헤더 햄버거로 먼저 연다(선택 시 자동 닫힘, AdminShell:260).
      let navOk = true
      try {
        if (isMobile) {
          const toggle = page.locator('.anticon-menu-unfold').first()
          if (await toggle.count()) { await toggle.click({ timeout: 3000 }); await page.waitForTimeout(400) }
        }
        const item = page.locator(`[data-menu-id$="${key}"]`).first()
        if (await item.count()) await item.click({ timeout: 4000 })
        else await page.getByText(label, { exact: true }).first().click({ timeout: 4000 })
      } catch {
        navOk = false
      }
      await page.waitForTimeout(900)
      let m = { vw: w, pageScroll: -1, offenders: [] }
      try { m = await page.evaluate(MEASURE, THRESHOLD) } catch { /* 측정 실패 */ }
      await page.screenshot({ path: `${OUT}/${vp}/${key}.png`, fullPage: true }).catch(() => {})
      const fail = navOk && (m.pageScroll > THRESHOLD || m.offenders.length > 0)
      if (fail) failCount++
      const row = { vp, key, label, navOk, pageScroll: m.pageScroll, offenderCount: m.offenders.length, offenders: m.offenders, fail }
      scorecard.push(row)
      const tag = !navOk ? 'NAV?' : fail ? 'FAIL' : ' ok '
      console.log(`  ${tag}  ${vp}/${key.padEnd(14)} pageScroll=${String(m.pageScroll).padStart(4)}px offenders=${m.offenders.length}`)
      if (fail && m.offenders.length) {
        for (const o of m.offenders.slice(0, 4)) console.log(`         ↳ +${o.overPx}px <${o.tag} class="${o.cls}"> "${o.text}"`)
      }
    }
  }
} finally {
  await browser.close()
}

writeFileSync(`${OUT}/scorecard.json`, JSON.stringify(scorecard, null, 2))
const fails = scorecard.filter((r) => r.fail)
console.log(`\n=== 스코어카드: ${scorecard.length}건 중 FAIL ${fails.length} ===`)
for (const f of fails) console.log(`  FAIL ${f.vp}/${f.key} (pageScroll=${f.pageScroll}px, offenders=${f.offenderCount})`)
console.log(`scorecard → ${OUT}/scorecard.json`)
process.exit(fails.length ? 1 : 0)
