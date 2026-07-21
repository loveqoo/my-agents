/* 어드민 "가이드" 메뉴 검증 — 도구 그룹에 메뉴가 보이고, 클릭 시 /guide/index.html이
   새 탭으로 열리며(뷰 전환 없음), 그 페이지에 한글 본문+스크린샷이 렌더된다. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1400, height: 950 } })
const page = await context.newPage()

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // G1: 가이드 메뉴가 도구 그룹에 보인다
  const guideItem = page.getByText('가이드', { exact: true }).first()
  ok((await guideItem.count()) > 0, 'G1 가이드 메뉴 노출')

  // G2: 클릭 → 새 탭(popup)으로 /guide/index.html
  const [popup] = await Promise.all([context.waitForEvent('page', { timeout: 10000 }), guideItem.click()])
  await popup.waitForLoadState('domcontentloaded')
  ok(popup.url().includes('/guide/index.html'), `G2 새 탭 URL=/guide/index.html (실제 ${popup.url()})`)

  // G3: 원래 탭의 뷰는 그대로(가이드가 뷰를 바꾸지 않음)
  const stillHome = await page.getByText('에이전트', { exact: true }).first().count()
  ok(stillHome > 0, 'G3 원래 탭 뷰 유지')

  // G4: 가이드 본문 한글 렌더 + 권한 섹션 + 이미지 로드
  const body = await popup.locator('body').innerText()
  ok(/노코드 에이전트 만들기 가이드/.test(body), 'G4a 제목 한글 정상')
  ok(/권한 이해하기/.test(body), 'G4b 권한 섹션 존재')
  const imgOk = await popup.evaluate(() =>
    Array.from(document.images).every((im) => im.complete && im.naturalWidth > 0))
  const imgCnt = await popup.evaluate(() => document.images.length)
  ok(imgOk && imgCnt === 9, `G4c 스크린샷 9장 전부 로드 (개수 ${imgCnt}, 로드 ${imgOk})`)
  await popup.screenshot({ path: `${OUT}/guide-page-top.png` })

  // G5: 상단 내비로 개발자 가이드 이동 — 제목·코드블록 렌더·내비 상호 링크
  await popup.locator('nav.guide-nav').getByRole('link', { name: '개발자 가이드' }).click()
  await popup.waitForLoadState('domcontentloaded')
  ok(popup.url().includes('/guide/developer.html'), `G5a 개발자 가이드 URL (실제 ${popup.url()})`)
  const devBody = await popup.locator('body').innerText()
  ok(/산출물형 에이전트 저작 가이드/.test(devBody), 'G5b 개발자 가이드 제목')
  const preCnt = await popup.locator('pre code').count()
  ok(preCnt >= 4, `G5c 코드블록 렌더 (pre>code ${preCnt}개)`)
  // 남은 .md 링크 0(전부 html 재작성/텍스트 강등)
  const mdLinks = await popup.evaluate(() =>
    Array.from(document.querySelectorAll('a')).filter((a) => a.getAttribute('href')?.endsWith('.md')).length)
  ok(mdLinks === 0, `G5d 잔존 .md 링크 0 (실제 ${mdLinks})`)
  await popup.screenshot({ path: `${OUT}/guide-dev-page.png` })
  // 내비로 노코드 가이드 복귀
  await popup.locator('nav.guide-nav').getByRole('link', { name: '노코드 가이드' }).click()
  await popup.waitForLoadState('domcontentloaded')
  ok(popup.url().includes('/guide/index.html'), 'G5e 내비 상호 링크(노코드 복귀)')
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (GUIDEMENU_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)
