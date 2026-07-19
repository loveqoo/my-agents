/* 첨부→지식 저장(스펙 405, B안) 기능 e2e — 외형이 아니라 기능:
   클립 드롭다운 → 지식으로 저장 → 새 컬렉션 생성 → 인제스트 ready 칩 → 질문 →
   응답이 문서 속 토큰을 근거로 + 메시지 메타에 rag 히트(검색 경유 증명).

   실행: PLAYWRIGHT_DIR=<pw> node tests/browser/verify-405-knowledge.mjs [out.png] */
import fs from 'node:fs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const VW = Number(process.env.VW ?? 1280)
const OUT = process.argv[2] ?? `/tmp/verify-405-knowledge-${VW}.png`

const TOKEN = 'NOVA-감귤-5521' // 문서에만 존재하는 토큰
const COL = `kb-v405-${Math.random().toString(36).slice(2, 8)}` // 스펙 148 이름 규칙 준수
const TMP = '/tmp/v405-knowledge-note.txt'
fs.writeFileSync(
  TMP,
  `신제품 출시 프로젝트의 비밀 코드네임은 ${TOKEN} 이다.\n담당 부서는 플랫폼팀이며 목표 분기는 4분기다.`,
)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: VW, height: 900 } })
const page = await ctx.newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  const pgMenu = page.getByText('Playground', { exact: true }).first()
  await page.waitForTimeout(1200)
  if (!(await pgMenu.isVisible().catch(() => false))) {
    await page.locator('button').first().click()
    await page.waitForTimeout(600)
  }
  await pgMenu.waitFor({ timeout: 10000 })
  await pgMenu.click()
  await page.waitForTimeout(2000)

  // 로컬(ui) 에이전트로 전환.
  const combo = page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first()
  await combo.click()
  await page.getByText('personal-secretary', { exact: false }).first().click()
  await page.waitForTimeout(1000)

  // ① 클립 드롭다운 → '지식으로 저장'
  await page.locator('.ant-sender button').first().click()
  await page.getByText('지식으로 저장', { exact: false }).click()
  await page.locator('input[type="file"]').setInputFiles(TMP)
  // ② 모달: 새 컬렉션 이름 입력 → 저장
  await page.locator('.ant-modal').getByText('지식으로 저장 (RAG)').waitFor({ timeout: 10000 })
  await page.getByPlaceholder(/새 컬렉션 이름/).fill(COL)
  await page.getByRole('button', { name: '저장' }).click()
  ok(true, '① 지식 저장 모달 → 새 컬렉션 이름 입력 → 저장')

  // ③ 인제스트 칩: 저장 중 → 배선됨(임베딩 포함 최대 120초)
  await page.getByText('이번 세션에 연결됨', { exact: false }).waitFor({ timeout: 120000 })
  ok(true, `② 인제스트 ready + 세션 연결 칩 (컬렉션 ${COL})`)

  // ④ 질문 → 검색 근거 답변(+메시지 메타 rag 히트)
  const input = page.getByPlaceholder(/에게 메시지/)
  await input.fill('신제품 출시 프로젝트의 비밀 코드네임이 뭐야? 코드네임만 정확히 답해줘.')
  await input.press('Enter')
  await page.getByText(TOKEN, { exact: false }).first().waitFor({ timeout: 120000 })
  ok(true, `③ 응답이 지식(문서) 속 토큰(${TOKEN})을 근거로 답함`)
  await page.waitForTimeout(1500) // 메타 배지 렌더 여유
  const ragBadge = await page.getByText(/[1-9] rag/, { exact: false }).count()
  ok(ragBadge > 0, `④ 메시지 메타에 rag 히트 배지(검색 경유 증명, got ${ragBadge})`)

  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT', OUT)
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
} finally {
  await browser.close()
}
console.log(fails.length ? `VERIFY405_BROWSER_FAIL(${fails.length})` : 'VERIFY405_BROWSER_OK')
process.exit(fails.length ? 1 : 0)
