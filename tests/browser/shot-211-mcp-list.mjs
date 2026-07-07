/* 스펙 211 검증 샷 — MCP 리스트 컬럼(이름+🔒/유형/소유/외부 서빙, 상태 없음) + 드로어(이름 1회).
   실행: PLAYWRIGHT_DIR=$PWD/tests/e2e/node_modules/playwright node tests/browser/shot-211-mcp-list.mjs */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { provisionSuper } from './_fixture.mjs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'out-211')
const BASE = process.env.ADMIN_URL || 'http://127.0.0.1:5173'
const { email, password } = provisionSuper()

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
let fails = 0
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
  if (!ok) fails++
}

await page.goto(BASE + '/')
await page.getByPlaceholder('you@example.com').fill(email)
await page.getByPlaceholder('비밀번호').fill(password)
await page.getByRole('button', { name: /로그인|login/i }).click()
await page.waitForTimeout(1500)

// 빌딩 블록 → MCP 서버 탭
await page.locator('[data-menu-id$="blocks"]').first().click()
await page.waitForTimeout(1000)
await page.getByRole('tab', { name: /MCP 서버/ }).click()
await page.waitForTimeout(900)

const headText = await page.locator('thead').first().innerText()
check('컬럼: 이름 존재', headText.includes('이름'))
check('컬럼: 유형 존재', headText.includes('유형'))
check('컬럼: 소유 존재', headText.includes('소유'))
check('컬럼: 외부 서빙 존재', headText.includes('외부 서빙'))
check('컬럼: 상태 부재', !headText.includes('상태'))
const bodyText = await page.locator('main, body').first().innerText()
check('행: 커스텀 태그 노출(web-fetch)', bodyText.includes('커스텀'))
await page.screenshot({ path: path.join(OUT, 'mcp-list.png'), fullPage: true })

// 드로어: web-fetch 행 클릭 → 이름 등장 횟수(타이틀 1회만)
const row = page.locator('tbody tr', { hasText: 'web-fetch' }).first()
await row.click({ position: { x: 300, y: 10 } }) // 이름 Tooltip·스위치 회피한 중립 좌표
await page.waitForTimeout(1200)
const drawer = page.locator('[role="dialog"]').first()  // antd v6 드로어 컨테이너
const dText = await drawer.innerText()
const nameCount = (dText.match(/web-fetch/g) || []).length
// 타이틀 1회 + 본문 code(도구 프리픽스 등) 허용이지만 헤더 중복 큰 글씨는 제거됨 —
// 정량: 드로어 헤더 영역(.ant-drawer-header) 1회 + 본문 첫 헤더 부재를 검사
const headerCount = ((await page.locator('.ant-drawer-header').innerText()).match(/web-fetch/g) || []).length
check('드로어 타이틀에 이름 1회', headerCount === 1, `header=${headerCount}`)
const bigName = await drawer.locator('div[style*="font-weight: 600"][style*="font-size: 16"]', { hasText: 'web-fetch' }).count()
check('드로어 본문 큰 이름 중복 부재', bigName === 0, `big=${bigName}`)
check('드로어: 외부 서빙 라벨(커스텀)', dText.includes('외부 서빙'))
check('드로어: 상태 표시 부재', !/상태/.test(dText))
await page.screenshot({ path: path.join(OUT, 'mcp-drawer.png'), fullPage: true })

await browser.close()
console.log(fails === 0 ? 'ALL PASS' : `${fails} FAIL`)
process.exit(fails === 0 ? 0 : 1)
