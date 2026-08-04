/* 스펙 308 기능 검증 — useAsyncData로 이관한 뷰들이 실제로 로드·재조회하는지 브라우저 왕복으로 확인.
   외형(라벨/렌더)만 보지 않고 **동작**을 단언한다(learning: UI 검증은 기능 왕복으로):
     · 개요(#1): Statistic 값이 실제 API 집계로 채워진다(카운트 ≥ 0, 스피너 잔류 없음).
     · 빌딩 블록(#5): getBlocks() → 탭들이 카운트 Tag와 함께 렌더, 탭 전환 동작.
     · RAG 컬렉션(#9): Promise.all 로드 정착(테이블 또는 빈 상태 — 로딩 스피너 잔류 없음).
     · 프로바이더·모델(#7·#8): 목록 로드 → 프로바이더 선택 → avail 모델 자동 재조회(체인+selectedId effect).
     · 평가(#10·#11): 문제집 드로어 → 케이스 로드, 성적표 드로어 → detail 로드(있으면).
   콘솔 에러 0(치명) 단언. 백엔드 무변경 — 순수 프론트 리팩터 회귀 그물.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-308-useasyncdata.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/verify-308.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const notes = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const note = (m) => { console.log('  ..  ' + m); notes.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
page.on('pageerror', (e) => consoleErrors.push('PAGEERROR: ' + e.message))
// 네트워크 감시 — useAsyncData deps 변경 시 실제 페치가 나가는지(외형 아닌 동작)를 URL로 증명.
const reqs = []
page.on('request', (r) => reqs.push(r.url()))
const since = () => reqs.length
const firedSince = (mark, re) => reqs.slice(mark).filter((u) => re.test(u))

const nav = async (label) => {
  await page.getByRole('menuitem', { name: label, exact: true }).first().click().catch(async () => {
    await page.getByText(label, { exact: true }).first().click()
  })
  await page.waitForTimeout(700)
}
const noSpinner = async (where) => {
  // antd Spin이 정착(로딩 스피너가 화면에 잔류하지 않음) — 무한 로딩/깨진 페치 감지.
  const spinning = await page.locator('.ant-spin-spinning').count()
  check(spinning === 0, `${where}: 로딩 스피너 정착(잔류 ${spinning})`)
}

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- #1 개요 ----------
  await nav('개요')
  await noSpinner('개요')
  const statVals = await page.locator('.ant-statistic-content-value').allInnerTexts()
  check(statVals.length >= 3, `개요: Statistic 타일 로드(${statVals.length}개: ${statVals.join('/')})`)
  // 값이 숫자로 채워졌는지(파생 data ?? 기본값이 렌더까지 흘렀는지) — '—'나 빈 문자열이 아닌 실측치.
  const numericTiles = statVals.filter((v) => /\d/.test(v)).length
  check(numericTiles >= 3, `개요: 값이 실제 숫자(${numericTiles}/${statVals.length} 타일)`)

  // ---------- #5 빌딩 블록 ----------
  await nav('빌딩 블록')
  await noSpinner('빌딩 블록')
  const tabs = await page.getByRole('tab').allInnerTexts()
  check(tabs.length >= 1, `블록: 탭 렌더(getBlocks→blocks 파생, ${tabs.length}개: ${tabs.join('|').slice(0, 80)})`)
  // 탭 라벨에 카운트 Tag가 박혀 있는지(blocks[k].items.length가 흘렀는지) — 숫자 포함 확인.
  const tabHasCount = tabs.some((t) => /\d/.test(t))
  check(tabHasCount, '블록: 탭에 항목 카운트 표시(items.length 파생)')
  if (tabs.length >= 2) {
    await page.getByRole('tab').nth(1).click()
    await page.waitForTimeout(500)
    await noSpinner('블록(탭전환)')
    check(true, '블록: 2번째 탭 전환 동작')
  }

  // ---------- #9 RAG 컬렉션 ----------
  await nav('RAG 컬렉션')
  await page.waitForTimeout(600)
  await noSpinner('컬렉션')
  // Promise.all([listCollections, listModels]) 정착 → 테이블 rows 또는 빈-상태 중 하나가 보여야 함.
  const colRows = await page.locator('.ant-table-tbody tr.ant-table-row').count()
  const colEmpty = await page.locator('.ant-empty').count()
  check(colRows > 0 || colEmpty > 0, `컬렉션: 로드 정착(행 ${colRows} / 빈상태 ${colEmpty})`)
  note(`컬렉션 행 수: ${colRows}`)

  // ---------- #7·#8 프로바이더·모델 ----------
  await page.getByText('프로바이더·모델', { exact: true }).first().click().catch(() => {})
  await page.waitForTimeout(900)
  await noSpinner('프로바이더')
  // 프로바이더 목록(체인 #7: loadRegModels→listProviders)이 실제로 페치됐는지.
  check(firedSince(0, /\/providers(\?|$)/).length > 0, '프로바이더: 목록 페치 발생(#7 체인 loadReg→listProviders)')
  // 마운트 시 providers[0]가 자동 선택돼 그 프로바이더의 available-models가 이미 1회 페치된다(selectedId
  // null→first effect + avail useAsyncData). 따라서 "각 클릭마다 페치"가 아니라 **선택이 실제로 바뀔 때
  // 마다 그 id로 avail가 재페치되는지**를 네트워크로 증명한다(#8 deps=[selectedId]).
  const provNames = ['Mock LLM', 'rapid-mlx']
  for (const name of provNames) {
    const row = page.getByText(name, { exact: true }).first()
    if (!(await row.count())) { note(`프로바이더 '${name}' 행 없음`); continue }
    await row.click()
    await page.waitForTimeout(1100)
    await noSpinner(`프로바이더(${name} 선택후)`)
    check(
      (await page.getByRole('heading', { name, exact: true }).count()) > 0,
      `프로바이더: '${name}' 선택 → 상세 패널 제목 갱신(selected 파생)`,
    )
  }
  // 전체 available-models 페치 URL들 — 마운트 자동선택 + 클릭 전환을 합쳐 서로 다른 프로바이더 id로
  // 최소 2회 나가야 한다(같은 id 반복이면 deps 반응이 아니라 우연). id 다양성으로 selectedId 반응 증명.
  const availUrls = reqs.filter((u) => /\/providers\/[^/]+\/available-models/.test(u))
  const availIds = new Set(availUrls.map((u) => u.match(/\/providers\/([^/]+)\/available-models/)?.[1]))
  note(`available-models 페치 ${availUrls.length}회, 고유 provider id ${availIds.size}종`)
  check(availUrls.length >= 2, `프로바이더: available-models 총 ${availUrls.length}회 페치(마운트+전환)`)
  check(availIds.size >= 2, `프로바이더: 서로 다른 provider id ${availIds.size}종으로 avail 재조회(#8 deps=[selectedId] 반응)`)

  // ---------- #10·#11 평가 드로어 ----------
  await nav('평가')
  await page.waitForTimeout(900)
  await noSpinner('평가')
  const evalTabs = await page.getByRole('tab').allInnerTexts()
  note(`평가 탭: ${evalTabs.join('|')}`)
  // 문제집 탭으로(기본이 아닐 수 있음) → 문제집 행 클릭(onRowClick=setDetail) → listEvalCases(#11).
  await page.getByRole('tab', { name: '문제집' }).click().catch(() => {})
  await page.waitForTimeout(600)
  const dsRows = await page.locator('.ant-table-row').count()
  note(`평가 문제집 행 수: ${dsRows}`)
  const dsRow = page.locator('.ant-table-row').first()
  if (dsRows > 0) {
    const mark = since()
    await dsRow.click()
    await page.waitForTimeout(1100)
    // #11의 진짜 게이트 = listEvalCases 페치(이관한 useAsyncData 코드경로 자체가 발화). 드로어 DOM은 보조.
    const casesFired = firedSince(mark, /\/eval\/datasets\/[^/]+\/cases/)
    check(casesFired.length > 0, '평가: 문제집 열기 → listEvalCases 페치(#11 DatasetDrawer useAsyncData 발화)')
    const drawerBody = await page.locator('.ant-drawer-body').count()
    note(`문제집 드로어 body ${drawerBody}개(보조)`)
    await noSpinner('평가(문제집 드로어)')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(500)
  } else {
    note('평가: 문제집 행 없음 — #11 미실증')
  }
  // 성적표(RunDrawer #10) — '실행 이력' 탭의 완료 런 행 클릭(onRowClick=setRunDetail) → getEvalRun 페치.
  await page.getByRole('tab', { name: '실행 이력' }).click().catch(() => {})
  await page.waitForTimeout(800)
  const runCount = await page.locator('.ant-table-row').count()
  note(`실행 이력 행 수: ${runCount}`)
  if (runCount > 0) {
    const mark = since()
    // 완료 런만 열린다(running 제외) — 여러 행을 시도해 하나라도 getEvalRun을 유발하면 성공.
    let opened = false
    const tryN = Math.min(runCount, 4)
    for (let i = 0; i < tryN && !opened; i++) {
      await page.locator('.ant-table-row').nth(i).click().catch(() => {})
      await page.waitForTimeout(700)
      if (firedSince(mark, /\/eval\/runs\/[^/]+$/).length > 0) opened = true
    }
    if (opened) {
      await noSpinner('평가(성적표 드로어)')
      check(true, '평가: 성적표 열기 → getEvalRun 페치(#10 RunDrawer useAsyncData 발화)')
      await page.keyboard.press('Escape')
      await page.waitForTimeout(400)
    } else {
      note('평가: 이력 행 클릭에도 getEvalRun 미발생(전부 running?) — #10 미실증')
    }
  } else {
    note('평가: 실행 이력 행 없음 — #10 미실증(데이터 사전조건)')
  }

  // ---------- 마감: 콘솔 에러 ----------
  await page.screenshot({ path: OUT, fullPage: false })
  // 무해한 잡음(네트워크 401 프리플라이트, antd deprecation 등) 제외 — 앱 크래시/렌더 예외만 치명.
  const fatal = consoleErrors.filter((e) =>
    /PAGEERROR|Cannot read|is not a function|undefined is not|Maximum update depth|Rendered more hooks|Rendered fewer hooks/i.test(e),
  )
  check(fatal.length === 0, `콘솔 치명 에러 0(전체 ${consoleErrors.length}, 치명 ${fatal.length})`)
  if (fatal.length) fatal.slice(0, 5).forEach((e) => console.log('    ! ' + e.slice(0, 160)))
} catch (e) {
  console.log('SCRIPT_ERROR: ' + (e?.stack ?? e))
  fails.push('스크립트 예외: ' + (e?.message ?? e))
} finally {
  await browser.close()
}

console.log('')
console.log(`스크린샷: ${OUT}`)
if (notes.length) console.log(`참고(미실증/데이터 사전조건): ${notes.length}건`)
if (fails.length) {
  console.log(`\nFAIL: ${fails.length}건`)
  fails.forEach((f) => console.log('  - ' + f))
  process.exit(1)
}
console.log('\nVERIFY308_OK — useAsyncData 이관 뷰 기능 왕복(로드·재조회·탭·드로어) 정착')
