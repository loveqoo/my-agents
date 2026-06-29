/* 스펙 066 검증(브라우저 rung) — resolve 인가 3-way의 *유저 가시* 경계를 캡처.
   member 로그인 → 승인 뷰: (1) 서버 스코핑으로 *자기* 행만 보이고, (2) 자기 민감 perm
   (data.delete) 행을 '승인 및 재개'하면 백엔드 403 → detail이 antd 토스트로 *도달*하며 카드는
   제거되지 않는다(실패 = 미실행 유지). D6는 프론트 무변경 — 이 rung은 기존 httpError+message.error
   글루가 새 백엔드 경계를 end-to-end로 노출함을 눈으로 확인한다(단위·라이브가 못 보는 UI 도달).

   백엔드 deny 매트릭스·스코핑 질의는 verify_066_live.py에서 실증 — 여기선 UI 도달만.
   던짐용 member + 합성 owned 행을 시드 → 종료 시 자동 삭제.
   실행: PLAYWRIGHT_DIR=<npx>/node_modules/playwright node tests/browser/shot-user-approval-066.mjs [outPrefix] */
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..')
const API_DIR = path.join(REPO, 'packages', 'api')
const PROV = path.join(REPO, 'tests', '_provision_super.py')
const SEED = path.join(REPO, 'tests', '_seed_approval_066.py')

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const PREFIX = process.argv[2] ?? '/tmp/user-approval-066'

const rand = Math.random().toString(36).slice(2, 10)
const MEMBER = { email: `shotfix_m${rand}@example.com`, password: 'Shotfix1!pw' }

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
py(SEED, ['seed', MEMBER.email, 'data.delete'])

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(MEMBER.email)
  await page.getByPlaceholder('비밀번호').fill(MEMBER.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(1000)

  // 승인 뷰 진입(배지가 라벨에 붙어 menuitem 정규식으로).
  await page.getByRole('menuitem', { name: /승인/ }).first().click()
  await page.waitForTimeout(1200)

  // (1) 스코핑: member는 자기 행 1개만. data.delete 태그·요약이 보인다.
  const cards = await page.getByRole('button', { name: '승인 및 재개' }).count()
  log('CARDS=' + cards, cards === 1 ? 'OK(자기 1개)' : 'FAIL')
  const hasPerm = await page.getByText('data.delete', { exact: false }).count()
  log('PERM_TAG=' + hasPerm, hasPerm >= 1 ? 'OK(data.delete 노출)' : 'FAIL')
  await page.screenshot({ path: `${PREFIX}-list.png`, fullPage: true })
  log('SHOT_LIST', `${PREFIX}-list.png`)

  // (2) resolve 시도 → 403 → antd message 토스트 detail 도달, 카드 잔존.
  await page.getByRole('button', { name: '승인 및 재개' }).first().click()
  await page.waitForTimeout(1400)
  const notice = page.locator('.ant-message-notice')
  const toastText = (await notice.count()) ? (await notice.first().innerText()).trim() : ''
  log('TOAST=' + JSON.stringify(toastText))
  const denied = toastText.includes('권한이 없습니다')
  log('TOAST_DENIED', denied ? 'OK(403 detail 도달)' : 'FAIL(detail 미도달)')
  const cardsAfter = await page.getByRole('button', { name: '승인 및 재개' }).count()
  log('CARDS_AFTER=' + cardsAfter, cardsAfter === 1 ? 'OK(잔존=미실행)' : 'FAIL(사라짐)')
  await page.screenshot({ path: `${PREFIX}-denied.png`, fullPage: true })
  log('SHOT_DENIED', `${PREFIX}-denied.png`)

  const pass = cards === 1 && hasPerm >= 1 && denied && cardsAfter === 1
  log(pass ? '✅ 066 BROWSER RUNG PASS' : '❌ 066 BROWSER RUNG FAIL')
} catch (e) {
  log('SHOT_FAIL', e.message)
  await page.screenshot({ path: `${PREFIX}-FAIL.png`, fullPage: true }).catch(() => {})
} finally {
  await browser.close()
}
