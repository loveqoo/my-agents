/* 스펙 053 검증 — 유저 메모리 역할 기반 스코핑의 *프론트 분기*를 캡처.
   member(비-super) 로그인: 유저 메모리 탭에 드롭다운 *없이* 본인 패널만.
   super 로그인: 임의 유저 선택 드롭다운 노출(스펙 052 UX 유지).

   백엔드 가드(타인 403)는 라이브 curl 통합에서 이미 실증 — 여기선 UI 분기만 본다.
   member·super 둘 다 던짐용 self-fixture로 시드 → 종료 시 자동 삭제.
   실행: PLAYWRIGHT_DIR=<npx>/node_modules/playwright node tests/browser/shot-memory-scoping-053.mjs [outPrefix] */
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..')
const API_DIR = path.join(REPO, 'packages', 'api')
const PROV = path.join(REPO, 'tests', '_provision_super.py')

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const PREFIX = process.argv[2] ?? '/tmp/memory-scoping-053'

const rand = Math.random().toString(36).slice(2, 10)
const MEMBER = { email: `shotfix_m${rand}@example.com`, password: 'Shotfix1!pw' }
const SUPER = { email: `shotfix_s${rand}@example.com`, password: 'Shotfix1!pw' }

function prov(args) {
  execFileSync('uv', ['run', 'python', PROV, ...args], { cwd: API_DIR, stdio: 'inherit' })
}
let torn = false
function teardown() {
  if (torn) return
  torn = true
  for (const u of [MEMBER, SUPER]) {
    try { prov(['delete', u.email]) } catch (e) { console.log('TEARDOWN_WARN', e?.message ?? e) }
  }
}
process.on('exit', teardown)
process.on('SIGINT', () => { teardown(); process.exit(130) })
process.on('SIGTERM', () => { teardown(); process.exit(143) })

prov(['create', MEMBER.email, MEMBER.password, 'member'])
prov(['create', SUPER.email, SUPER.password]) // super

const browser = await chromium.launch({ channel: 'chrome', headless: true })

async function openUserMemoryTab(page, who) {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(who.email)
  await page.getByPlaceholder('비밀번호').fill(who.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(600)
  await page.getByRole('tab', { name: '유저 메모리' }).click()
  await page.waitForTimeout(800)
}

try {
  // ---- member: 드롭다운 없어야 함 ----
  const mctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 900 } })
  const mp = await mctx.newPage()
  await openUserMemoryTab(mp, MEMBER)
  const memberSelects = await mp.locator('.ant-tabs-tabpane-active .ant-select').count()
  console.log('MEMBER_DROPDOWN_COUNT', memberSelects, memberSelects === 0 ? 'OK(없음)' : 'FAIL(있음)')
  const memberHeader = await mp.locator('text=회상됩니다').first().innerText().catch(() => '')
  console.log('MEMBER_PANEL_HEADER', JSON.stringify(memberHeader.slice(0, 90)))
  console.log('MEMBER_HEADER_HAS_EMAIL', memberHeader.includes(MEMBER.email) ? 'OK' : 'MISS')
  await mp.screenshot({ path: `${PREFIX}-member.png`, fullPage: true })
  console.log('SHOT_MEMBER', `${PREFIX}-member.png`)
  await mctx.close()

  // ---- super: 드롭다운 있어야 함 ----
  const sctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 900 } })
  const sp = await sctx.newPage()
  await openUserMemoryTab(sp, SUPER)
  const superSelects = await sp.locator('.ant-tabs-tabpane-active .ant-select').count()
  console.log('SUPER_DROPDOWN_COUNT', superSelects, superSelects >= 1 ? 'OK(있음)' : 'FAIL(없음)')
  await sp.screenshot({ path: `${PREFIX}-super.png`, fullPage: true })
  console.log('SHOT_SUPER', `${PREFIX}-super.png`)
  await sctx.close()
} catch (e) {
  console.log('SHOT_FAIL', e.message)
} finally {
  await browser.close()
}
