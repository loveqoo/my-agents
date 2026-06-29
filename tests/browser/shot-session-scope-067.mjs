/* 스펙 067 검증(브라우저 rung) — 세션 유저 스코핑의 *유저 가시* 경계를 캡처.
   member 로그인 → 세션 뷰: (1) 서버 스코핑으로 *자기* 세션만 테이블에 뜨고 타인 세션은 숨으며,
   (2) 배지 '전체 (N)'이 본인 세션 수만 센다. D6는 프론트 무변경 — 이 rung은 SessionsView가 GET
   /sessions(스코핑됨)를 그대로 렌더해 타인 대화가 UI까지 새지 않음을 눈으로 확인한다(단위·라이브가
   못 보는 UI 도달).

   백엔드 스코핑·404 은폐는 verify_067_live.py에서 실증 — 여기선 UI 도달만.
   던짐용 member + 합성 own/other 세션을 시드 → 종료 시 자동 삭제.
   실행: PLAYWRIGHT_DIR=<npx>/node_modules/playwright node tests/browser/shot-session-scope-067.mjs [outPrefix] */
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..')
const API_DIR = path.join(REPO, 'packages', 'api')
const PROV = path.join(REPO, 'tests', '_provision_super.py')
const SEED = path.join(REPO, 'tests', '_seed_session_067.py')

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const PREFIX = process.argv[2] ?? '/tmp/session-scope-067'

const rand = Math.random().toString(36).slice(2, 10)
const MEMBER = { email: `shotfix_s067m${rand}@example.com`, password: 'Shot067!pw' }
const OWN = 'sess-067shot-own'
const OTHER = 'sess-067shot-other'

function py(script, args) {
  return execFileSync('uv', ['run', 'python', script, ...args], { cwd: API_DIR, encoding: 'utf8' })
}
let torn = false
function teardown() {
  if (torn) return
  torn = true
  try { py(SEED, ['unseed']) } catch (e) { console.log('TEARDOWN_WARN seed', e?.message ?? e) }
  try { py(PROV, ['delete', MEMBER.email]) } catch (e) { console.log('TEARDOWN_WARN user', e?.message ?? e) }
}
process.on('exit', teardown)
process.on('SIGINT', () => { teardown(); process.exit(130) })
process.on('SIGTERM', () => { teardown(); process.exit(143) })

py(PROV, ['create', MEMBER.email, MEMBER.password, 'member'])
py(SEED, ['seed', MEMBER.email])

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(MEMBER.email)
  await page.getByPlaceholder('비밀번호').fill(MEMBER.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)

  // 세션 뷰 진입.
  await page.getByRole('menuitem', { name: /세션/ }).first().click()
  await page.waitForTimeout(1200)

  // (1) 스코핑: 자기 세션(OWN)만 테이블에 뜨고 타인(OTHER)은 안 뜬다.
  const ownVisible = await page.getByText(OWN, { exact: false }).count()
  const otherVisible = await page.getByText(OTHER, { exact: false }).count()
  log('OWN_VISIBLE=' + ownVisible, ownVisible >= 1 ? 'OK(자기 세션 노출)' : 'FAIL')
  log('OTHER_VISIBLE=' + otherVisible, otherVisible === 0 ? 'OK(타인 세션 숨김)' : 'FAIL(타인 누출!)')

  // (2) 배지 '전체 (N)' — 본인 세션만 집계(fresh member라 정확히 1).
  const allLabel = (await page.getByText(/전체 \(\d+\)/).first().innerText()).trim()
  log('BADGE=' + JSON.stringify(allLabel))
  const badgeOne = /전체 \(1\)/.test(allLabel)
  log('BADGE_SCOPED', badgeOne ? 'OK(전체 (1)=본인만)' : 'FAIL(전역 누설)')

  await page.screenshot({ path: `${PREFIX}-list.png`, fullPage: true })
  log('SHOT_LIST', `${PREFIX}-list.png`)

  const pass = ownVisible >= 1 && otherVisible === 0 && badgeOne
  log(pass ? '✅ 067 BROWSER RUNG PASS' : '❌ 067 BROWSER RUNG FAIL')
  process.exitCode = pass ? 0 : 1
} catch (e) {
  log('SHOT_FAIL', e.message)
  await page.screenshot({ path: `${PREFIX}-FAIL.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
