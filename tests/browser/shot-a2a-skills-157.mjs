/* 스펙 157 e2e — A2A 카드 "광고 스킬" 표시(플레이그라운드 A2A 모드) 브라우저 검증.
   (K1) 플레이그라운드 진입 → 에이전트 피커에서 "Research Assistant"(research-assistant, ui,
        exposed.a2a=True, MCP 서버 local-tools 사용) 선택 → 헤더에 "직접"/"A2A" Segmented 토글이 보인다.
   (K2) 토글에서 "A2A" 클릭 → 선택 상태로 전환되고, 배너에 "A2A 경유 테스트 — 단발 호출" 안내가 보인다.
   (K3) 같은 배너에 "광고 스킬:" 레이블과 함께 MCP 도구 칩(web_search/echo/delete_record 중 최소 1개)이
        표시된다(스펙 157 — 카드가 광고하는 실제 능력). 칩은 fetch 후 비동기 렌더라 최대 10초 폴링.
   (K4) 토글을 "직접"으로 되돌리면 "광고 스킬" 배너(및 A2A 배너 전체)가 사라진다.

   앱 코드 수정 없음 — 검증 전용. 앱 상태 불변(research-assistant 노출 상태 그대로, 메시지 전송 없이
   토글·칩 표시만 확인). 템플릿=shot-playground-a2a-155.mjs(로그인·PLAYWRIGHT_DIR·pickAgent·Segmented
   antd6 관례 그대로 재사용 — Segmented는 `.ant-segmented-item`이지 버튼이 아니다).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-a2a-skills-157.mjs */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..')
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_DIR = path.join(__dirname, 'out-157')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message))

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

// AgentCombo 트리거는 "현재 선택된" 에이전트 이름을 보여준다(목표 에이전트 이름이 아님) —
// 목표 이름으로 트리거를 찾으면 아직 안 바뀐 상태에선 못 찾는다. 그래서 트리거는 시드
// 에이전트 5종 이름 중 아무거나(현재 활성) 매칭하는 공통 정규식으로 열고, 드롭다운이 열린
// 뒤에만 목표 이름으로 행을 골라 클릭한다.
const ANY_SEED_AGENT_RE = /research-assistant|personal-secretary|doc-translator|acme-translate-a2a|plan-execute-demo/i
async function pickAgent(agentNameSubstr) {
  const trigger = page.getByRole('button', { name: ANY_SEED_AGENT_RE }).first()
  await trigger.waitFor({ timeout: 10000 })
  await trigger.click()
  await page.waitForTimeout(300)
  // 드롭다운 안에서 목표 이름의 행을 클릭(스스로 닫힘 — onSwitch → setOpen(false)).
  const row = page.locator('button', { hasText: new RegExp(agentNameSubstr, 'i') }).last()
  await row.waitFor({ timeout: 10000 })
  await row.click()
  await page.waitForTimeout(500)
}

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- 플레이그라운드 진입(state 라우팅 — 메뉴 텍스트 클릭) ----------
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  // ================= K1: "Research Assistant" 선택 → "직접"/"A2A" Segmented 노출 =================
  await pickAgent('research-assistant')
  const segmented = page.locator('.ant-segmented').filter({ hasText: '직접' }).filter({ hasText: 'A2A' })
  const segmentedShown = await segmented.first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  check(segmentedShown, 'K1: "Research Assistant" 선택 후 헤더에 "직접"/"A2A" Segmented 토글 표시')
  await shot('01-research-assistant-toggle')

  // ================= K2: "A2A" 클릭 → 선택 상태 전환 + "A2A 경유 테스트 — 단발 호출" 배너 =================
  const a2aItem = segmented.locator('.ant-segmented-item', { hasText: 'A2A' }).first()
  await a2aItem.waitFor({ timeout: 5000 })
  await a2aItem.click()
  const a2aSelected = await page
    .waitForFunction(
      () => {
        const items = document.querySelectorAll('.ant-segmented .ant-segmented-item')
        const target = Array.from(items).find((el) => el.textContent?.includes('A2A'))
        return !!target && target.classList.contains('ant-segmented-item-selected')
      },
      { timeout: 2000, polling: 100 },
    )
    .then(() => true)
    .catch(() => false)
  check(a2aSelected, `K2a: "A2A" 클릭 후 선택 상태(class=ant-segmented-item-selected)로 전환(실측=${a2aSelected})`)

  const bannerShown = await page
    .getByText('A2A 경유 테스트 — 단발 호출', { exact: false })
    .first()
    .waitFor({ timeout: 5000 })
    .then(() => true)
    .catch(() => false)
  check(bannerShown, 'K2b: "A2A 경유 테스트 — 단발 호출" 안내 배너 표시')
  await shot('02-a2a-banner')

  // ================= K3: "광고 스킬:" 레이블 + MCP 도구 칩(web_search/echo/delete_record 중 1개 이상,
  //                        chat 필요X) — fetch 비동기라 최대 10초 폴링 =================
  const skillsLabelShown = await page
    .getByText('광고 스킬:', { exact: false })
    .first()
    .waitFor({ timeout: 10000 })
    .then(() => true)
    .catch(() => false)
  check(skillsLabelShown, 'K3a: "광고 스킬:" 레이블 표시(최대 10초 폴링)')

  const SKILL_TAG_RE = /web_search|echo|delete_record/
  let skillChipShown = false
  let matchedSkills = []
  if (skillsLabelShown) {
    skillChipShown = await page
      .waitForFunction(
        (pattern) => {
          const tags = Array.from(document.querySelectorAll('.ant-tag'))
          return tags.some((t) => new RegExp(pattern).test(t.textContent || ''))
        },
        SKILL_TAG_RE.source,
        { timeout: 10000, polling: 300 },
      )
      .then(() => true)
      .catch(() => false)
    if (skillChipShown) {
      matchedSkills = await page.evaluate((pattern) => {
        const tags = Array.from(document.querySelectorAll('.ant-tag'))
        return tags.map((t) => (t.textContent || '').trim()).filter((t) => new RegExp(pattern).test(t))
      }, SKILL_TAG_RE.source)
    }
  }
  check(skillChipShown, `K3b: MCP 도구 칩(web_search/echo/delete_record 중 1개 이상) 표시(실측=${JSON.stringify(matchedSkills)})`)
  await shot('03-a2a-skills-chips')

  // ================= K4: "직접"으로 되돌리면 "광고 스킬" 배너 사라짐 =================
  const directItem = segmented.locator('.ant-segmented-item', { hasText: '직접' }).first()
  await directItem.click()
  const skillsLabelGone = await page
    .waitForFunction(
      () => !Array.from(document.querySelectorAll('span')).some((s) => (s.textContent || '').includes('광고 스킬:')),
      { timeout: 5000, polling: 200 },
    )
    .then(() => true)
    .catch(() => false)
  check(skillsLabelGone, 'K4: "직접"으로 되돌린 후 "광고 스킬" 배너 부재')
  await shot('04-direct-no-skills-banner')

  const fatalErrors = consoleErrors.filter((e) => /50\d|crash|Uncaught/i.test(e))
  console.log(
    consoleErrors.length
      ? `CONSOLE_ERRORS(${consoleErrors.length}, fatal=${fatalErrors.length}) ` + JSON.stringify(consoleErrors.slice(0, 10))
      : 'NO_CONSOLE_ERRORS',
  )
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)
