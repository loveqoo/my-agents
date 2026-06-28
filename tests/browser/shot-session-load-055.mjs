/* 스펙 055 후속 — 메시지 0개 세션을 고르면 '불러올 메시지 없음' 빈 상태가 뜨는지.
   (메시지 있는 세션의 히스토리 렌더는 shot-resume-session-055의 marker 복원이 커버.)

   사용자 보고: 세션을 골라도 아무것도 안 나온다 → 시드/레거시 세션은 turns>0이지만
   Message 0행이라 불러올 게 없는데, 새 대화 프롬프트 카드와 똑같이 보여 깨진 듯했다.
   이제 명시적 빈 상태('이 세션에는 불러올 메시지가 없습니다')로 구분되어야 한다.

   실행: PLAYWRIGHT_DIR=<abs> node tests/browser/shot-session-load-055.mjs /tmp/sload */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/sload'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const errs = []
page.on('pageerror', (e) => errs.push(e.message))
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1500)

  // 세션 피커 열기.
  await page.locator('button[title^="세션 — 과거 대화"]').click()
  await page.waitForTimeout(900)
  // 드롭다운에서 'sess-'로 시작하는 행(= preview 없는 시드/레거시 세션) 클릭.
  const dropdown = page.locator('div[style*="overflow: auto"]').last()
  const rows = dropdown.locator('button')
  const texts = await rows.allInnerTexts()
  const seededIdx = texts.findIndex((t) => t.trim().startsWith('sess-'))
  log('rows=' + JSON.stringify(texts.map((t) => t.replace(/\n/g, ' ').slice(0, 40))))
  if (seededIdx < 0) throw new Error('preview 없는 시드 세션 행을 찾지 못함(데이터 상태 확인 필요)')
  await rows.nth(seededIdx).click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}-empty.png`, fullPage: true })
  const body = await page.locator('body').innerText()
  const showsEmptyState = body.includes('불러올 메시지가 없습니다')
  // 새 대화 프롬프트 카드가 아니어야(구분됨).
  const notPromptCards = !body.includes('디버그 프롬프트 체험')
  log('EMPTY_STATE shown=' + showsEmptyState + ' not_prompt_cards=' + notPromptCards)
  log(showsEmptyState && notPromptCards ? 'SLOAD_OK' : 'SLOAD_SUSPECT')
  log('PAGE_ERRORS=' + JSON.stringify(errs.slice(0, 5)))
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  log('PAGE_ERRORS=' + JSON.stringify(errs.slice(0, 5)))
  process.exitCode = 1
} finally {
  await browser.close()
}
