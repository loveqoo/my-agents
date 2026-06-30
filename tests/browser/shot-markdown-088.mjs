/* 스펙 088 — markdown/JSON 렌더 DOM 단언(시스템 Chrome). 하니스 페이지
   (/_harness_088.html)에서 실제 MessageContent를 마운트해 검증한다.
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-markdown-088.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = (process.env.ADMIN_URL ?? 'http://127.0.0.1:5173') + '/_harness_088.html'
const OUT = process.argv[2] ?? '/tmp/markdown-088.png'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 760, height: 1400 } })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

const fails = []
const check = (cond, msg) => {
  console.log((cond ? '  ok  ' : ' FAIL ') + msg)
  if (!cond) fails.push(msg)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForTimeout(600)

  const md = page.getByTestId('md')
  const json = page.getByTestId('json')
  const jsonStream = page.getByTestId('json-streaming')
  const num = page.getByTestId('num')
  const mdImg = page.getByTestId('md-img')
  const jsonBigint = page.getByTestId('json-bigint')
  const jsonDeep = page.getByTestId('json-deep')

  // [A] markdown(settled): 실제 DOM 요소로 렌더(평문 아님).
  check((await md.locator('.md-body strong').count()) >= 1, 'A1 **굵게** → <strong>')
  check((await md.locator('.md-body em').count()) >= 1, 'A2 *기울임* → <em>')
  check((await md.locator('.md-body h2').count()) >= 1, 'A3 ## 제목 → <h2>')
  check((await md.locator('.md-body li').count()) >= 2, 'A4 목록 → <li> 2+')
  check((await md.locator('.md-body table').count()) >= 1, 'A5 표 → <table>')
  check((await md.locator('.md-body pre code').count()) >= 1, 'A6 코드펜스 → <pre><code>')
  const aHref = await md.locator('.md-body a').first().getAttribute('href')
  check(aHref === 'https://example.com', 'A7 링크 href 보존(안전 URL)')
  // 평문 마크업 잔존 0(텍스트에 literal ** 가 안 보임).
  const mdText = await md.innerText()
  check(!mdText.includes('**굵게**'), 'A8 literal ** 잔존 0')
  // JSON 트리(caret)는 markdown 블록엔 없음.
  check((await md.getByText('▾', { exact: false }).count()) === 0, 'A9 markdown 블록에 트리 caret 없음')

  // [B] json doc(settled): 트리로 렌더(markdown 표/strong 아님).
  check((await json.getByText('▾', { exact: false }).count()) >= 1, 'B1 json 문서 → 트리 caret(▾)')
  check((await json.getByText('"name"', { exact: false }).count()) >= 1, 'B2 키 "name" 표시')
  check((await json.locator('.md-body').count()) === 0, 'B3 json 블록은 markdown(.md-body) 아님')
  check((await json.locator('table, strong').count()) === 0, 'B4 json 블록에 표/strong 없음')

  // [C] 스트리밍 중 부분 JSON → markdown 경로(트리 깜빡임 차단).
  check((await jsonStream.locator('.md-body').count()) === 1, 'C1 streaming partial json → markdown(.md-body)')
  check((await jsonStream.getByText('▾', { exact: false }).count()) === 0, 'C2 streaming 중 트리 caret 없음')

  // [D] bare 42(settled) → markdown(거짓양성 차단, 트리 아님).
  check((await num.locator('.md-body').count()) === 1, 'D1 bare 42 → markdown(.md-body)')
  check((await num.getByText('▾', { exact: false }).count()) === 0, 'D2 bare 42 트리 아님')

  // [E] codex F3: markdown 이미지 → 자동로드 차단(<img> 없음, 링크로 치환).
  check((await mdImg.locator('img').count()) === 0, 'E1 <img> 미렌더(원격 자동로드 차단)')
  const imgHref = await mdImg.locator('a').first().getAttribute('href')
  check(imgHref === 'http://evil.example/pixel.gif', 'E2 src는 링크 href로 보존(클릭은 사용자 의도)')
  check((await mdImg.getByText('추적픽셀', { exact: false }).count()) >= 1, 'E3 alt 텍스트 노출')

  // [F] codex F4: 16자리+ 정수 → 트리 아닌 원문 pre 폴백(정밀도 보존).
  check((await jsonBigint.getByText('▾', { exact: false }).count()) === 0, 'F1 bigint은 트리 caret 없음')
  check((await jsonBigint.locator('pre').count()) === 1, 'F2 원문 pre로 폴백')
  check((await jsonBigint.innerText()).includes('9007199254740993'), 'F3 원문 정수 verbatim 보존')

  // [G] codex F2: 깊은 중첩 → 크래시/콘솔에러 없이 트리 렌더(MAX_DEPTH 가드).
  check((await jsonDeep.getByText('▾', { exact: false }).count()) >= 1, 'G1 깊은 JSON도 트리로 렌더(크래시 없음)')

  await page.screenshot({ path: OUT, fullPage: true })
  console.log('\nSHOT', OUT)
  if (errors.length) console.log('CONSOLE_ERRORS', JSON.stringify(errors.slice(0, 8)))
} catch (e) {
  console.log('HARNESS_FAIL', e.message)
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  fails.push('harness:' + e.message)
} finally {
  await browser.close()
}

if (fails.length) {
  console.log(`\nFAILED (${fails.length})`)
  process.exit(1)
}
console.log('\nALL GREEN (088 browser)')
