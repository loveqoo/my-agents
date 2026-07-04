/* 스펙 168 — 드로어·모달 오버플로 감사(검증 축2 확장). ui-audit.mjs(스펙 165)의 로그인·네비 패턴과
   MEASURE 함수(오버플로 판정)를 그대로 재사용해, 화면 자체가 아니라 **오버레이(모달/드로어/패널)**를
   열어둔 채로 같은 기준으로 측정한다. 오버레이는 화면 위에 얹히므로 화면 자체 감사(165)로는 안 잡힌다.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/ui-audit-overlays.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
import { mkdirSync, writeFileSync } from 'node:fs'

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? 'tests/browser/out-overlay'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const THRESHOLD = 4 // px

const VIEWPORTS = [
  ['mobile', 360, 780],
  ['desktop', 1280, 900],
]

// MEASURE — tests/browser/ui-audit.mjs(스펙 165)에서 그대로 복사(출처 명시, 브리프 지시).
// rect.right>vw 초과 요소를 오프더(offender)로 잡는다. 화면밖(left>=vw)·antd 탭(.ant-tabs-nav
// 흡수)·의도적 스크롤 컨테이너(auto/scroll/hidden)는 제외(오탐 컷). 판정 임계 4px.
const MEASURE = (threshold) => {
  const de = document.documentElement
  const vw = de.clientWidth
  const vh = window.innerHeight || de.clientHeight
  const pageScroll = de.scrollWidth - vw
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
    if (r.bottom < 0 || r.top > vh) continue
    if (r.left >= vw - threshold) continue
    if (absorbed(el)) continue
    const past = Math.round(r.right - vw)
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

// 화면 네비 — ui-audit.mjs와 동일: data-menu-id가 key로 끝난다. 모바일은 Sider가 오버레이(기본
// 닫힘)라 헤더 햄버거로 먼저 연다(선택 시 자동 닫힘).
// 주의(이 스펙에서 발견): 기본 view가 이미 'agents'라 그 메뉴 항목을 다시 눌러도 antd Menu의
// onSelect가 재발화하지 않아 백드롭이 안 닫히는 경우가 있다 — 잔여 마스크를 직접 눌러 닫는다.
// 마스크(AdminShell) 중앙은 사이더(232px)에 가려 클릭이 먹지 않으므로 사이더 밖 좌표를 명시 클릭.
async function navTo(page, key, isMobile) {
  if (isMobile) {
    const toggle = page.locator('.anticon-menu-unfold').first()
    if (await toggle.count()) {
      await toggle.click({ timeout: 3000 })
      await page.waitForTimeout(400)
    }
  }
  const item = page.locator(`[data-menu-id$="${key}"]`).first()
  await item.click({ timeout: 4000 })
  await page.waitForTimeout(700)
  if (isMobile) {
    const mask = page.locator('div[style*="rgba(0, 0, 0, 0.45)"]')
    if (await mask.count()) {
      await page.mouse.click(300, 400) // 사이더(폭 232) 밖 좌표 — 백드롭 onClick으로 닫힘
      await page.waitForTimeout(300)
    }
  }
}

// 목록 첫 행 클릭 — 데스크톱은 <table>, 모바일(스펙 145: lg 미만)은 DataTable이 카드로 렌더되어
// <table>이 아예 없다(이 스펙에서 실측 확인). 카드는 onRowClick 시 inline cursor:pointer를 건다.
async function clickFirstRow(page, isMobile) {
  if (isMobile) {
    const card = page.locator('.ant-layout-content [style*="cursor: pointer"]').first()
    await card.waitFor({ timeout: 4000 })
    await card.click({ timeout: 4000 })
  } else {
    const row = page.locator('table tbody tr').first()
    await row.waitFor({ timeout: 4000 })
    await row.click({ timeout: 4000 })
  }
}

// 오버레이 정의 — 각 open()은 네비까지 마친 뒤 열기 동작만 수행하고 열림을 기다린다(600ms는
// 호출부 공통 처리). 실패하면 예외를 던져 navOk=false로 기록된다.
const OVERLAYS = [
  {
    key: 'agent-create',
    async open(page, isMobile) {
      await navTo(page, 'agents', isMobile)
      await page.getByRole('button', { name: /새 에이전트/ }).first().click({ timeout: 4000 })
      await page.locator('.ant-modal').first().waitFor({ timeout: 4000 })
    },
  },
  {
    key: 'agent-detail',
    async open(page, isMobile) {
      await navTo(page, 'agents', isMobile)
      await clickFirstRow(page, isMobile)
    },
  },
  {
    key: 'persona-edit',
    async open(page, isMobile) {
      await navTo(page, 'blocks', isMobile) // 페르소나가 기본 탭(BlocksView cat='persona')
      await clickFirstRow(page, isMobile)
      await page.waitForTimeout(500) // 상세 드로어 열림
      // exact 매칭 금지 — antd Button 아이콘의 role=img aria-label(예: "edit")이 접근성 이름 앞에
      // 붙어("edit 편집") exact:true가 깨진다(이 스펙에서 실측). 부분일치로 통일.
      await page.getByRole('button', { name: /편집/ }).first().click({ timeout: 4000 })
      await page.locator('.ant-modal').first().waitFor({ timeout: 4000 })
    },
  },
  {
    key: 'collection-create',
    async open(page, isMobile) {
      await navTo(page, 'collections', isMobile)
      const btn = page.getByRole('button', { name: /컬렉션 생성/ }).first()
      await btn.waitFor({ timeout: 4000 })
      if (await btn.isDisabled()) throw new Error('버튼 비활성(임베딩 모델 미등록)')
      await btn.click({ timeout: 4000 })
      await page.locator('.ant-modal').first().waitFor({ timeout: 4000 })
    },
  },
  {
    key: 'provider-add',
    async open(page, isMobile) {
      await navTo(page, 'models', isMobile)
      await page.getByRole('button', { name: /프로바이더\s*(등록|추가)/ }).first().click({ timeout: 4000 })
      await page.locator('.ant-modal').first().waitFor({ timeout: 4000 })
    },
  },
  {
    key: 'pg-override',
    async open(page, isMobile) {
      await navTo(page, 'debug', isMobile)
      const btn = page.locator('button[title^="런타임 오버라이드"]').first()
      await btn.waitFor({ timeout: 6000 }) // 에이전트 자동 선택 대기(마운트 시 첫 에이전트)
      await btn.click({ timeout: 4000 })
      await page.locator('.ant-drawer').first().waitFor({ timeout: 4000 })
    },
  },
  {
    key: 'pg-inspector',
    async open(page, isMobile) {
      await navTo(page, 'debug', isMobile)
      const btn = page.locator('button[title="인스펙터"]').first()
      await btn.waitFor({ timeout: 6000 })
      await btn.click({ timeout: 4000 })
    },
  },
]

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const scorecard = []
let failCount = 0

try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await ctx.newPage()
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
    for (const ov of OVERLAYS) {
      let navOk = true
      let navReason = ''
      try {
        await ov.open(page, isMobile)
      } catch (e) {
        navOk = false
        navReason = e?.message ?? String(e)
      }
      // 브리프 지시: 열기 후 waitForTimeout(600) 후 측정(트랜지션 정착 대기).
      await page.waitForTimeout(600)
      let m = { vw: w, pageScroll: -1, offenders: [] }
      try {
        m = await page.evaluate(MEASURE, THRESHOLD)
      } catch { /* 측정 실패 — pageScroll -1로 표시 */ }
      await page.screenshot({ path: `${OUT}/${vp}/${ov.key}.png`, fullPage: true }).catch(() => {})
      // 닫기: Escape(antd Modal/Drawer 기본 keyboard=true, 커스텀 Drawer·Inspector도 Escape 리스너 보유).
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(300)
      // 화면 전환 전 잔여 오버레이(예: persona-edit의 상세 드로어) 정리 — 한 번 더 Escape.
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(200)

      const fail = navOk && (m.pageScroll > THRESHOLD || m.offenders.length > 0)
      if (fail) failCount++
      const row = {
        key: ov.key,
        vp,
        navOk,
        navReason: navOk ? undefined : navReason,
        pageScroll: m.pageScroll,
        offenderCount: m.offenders.length,
        offenders: m.offenders,
        fail,
      }
      scorecard.push(row)
      const tag = !navOk ? 'NAV?' : fail ? 'FAIL' : ' ok '
      console.log(`  ${tag}  ${vp}/${ov.key.padEnd(16)} pageScroll=${String(m.pageScroll).padStart(4)}px offenders=${m.offenders.length}${navOk ? '' : ' reason=' + navReason}`)
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
const navFails = scorecard.filter((r) => !r.navOk)
console.log(`\n=== 스코어카드: ${scorecard.length}건 중 FAIL ${fails.length}, NAV 실패 ${navFails.length} ===`)
for (const f of fails) console.log(`  FAIL ${f.vp}/${f.key} (pageScroll=${f.pageScroll}px, offenders=${f.offenderCount})`)
for (const f of navFails) console.log(`  NAV?  ${f.vp}/${f.key} — ${f.navReason}`)
console.log(`scorecard → ${OUT}/scorecard.json`)
process.exit(fails.length ? 1 : 0)
