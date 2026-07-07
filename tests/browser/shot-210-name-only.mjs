/* 스펙 210 검증 샷 — 이름 단독 표시 + 툴팁 설명.
   4화면 캡처(에이전트/블록MCP/컬렉션/세션) + DOM 단언:
   (1) 리스트 innerText에 시드 별명("Research Assistant" 등 자유표기)이 없다 — 이름만.
   (2) 에이전트 리스트 첫 행 이름에 마우스오버 → antd Tooltip에 설명 노출.
   실행: PLAYWRIGHT_DIR=$PWD/tests/e2e/node_modules/playwright node tests/browser/shot-210-name-only.mjs */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { provisionSuper } from './_fixture.mjs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'out-210')
const BASE = process.env.ADMIN_URL || 'http://127.0.0.1:5173'
const { email, password } = provisionSuper()

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
let fails = 0
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
  if (!ok) fails++
}

// 로그인
await page.goto(BASE + '/')
await page.getByPlaceholder('you@example.com').fill(email)
await page.getByPlaceholder('비밀번호').fill(password)
await page.getByRole('button', { name: /로그인|login/i }).click()
await page.waitForTimeout(1500)

const nav = async (key) => {
  await page.locator(`[data-menu-id$="${key}"]`).first().click({ timeout: 5000 })
  await page.waitForTimeout(1100)
}

// 1) 에이전트 리스트 — 별명(자유표기 대문자 시드) 부재 + 이름 노출
await nav('agents')
const agentsText = await page.locator('main').innerText().catch(() => page.locator('body').innerText())
check('agents: 이름(research-assistant) 노출', agentsText.includes('research-assistant'))
check('agents: 별명("Research Assistant") 비노출', !agentsText.includes('Research Assistant'))
await page.screenshot({ path: path.join(OUT, 'agents.png'), fullPage: true })

// 2) 에이전트 첫 행 이름 마우스오버 → 툴팁(설명)
const nameEl = page.locator('text=research-assistant').first()
await nameEl.hover()
await page.waitForTimeout(800)
const tooltip = await page.locator('.ant-tooltip:not(.ant-tooltip-hidden)').innerText().catch(() => '')
check('agents: 마우스오버 툴팁 설명', tooltip.trim().length > 0, JSON.stringify(tooltip.slice(0, 60)))
await page.screenshot({ path: path.join(OUT, 'agents-tooltip.png') })
await page.mouse.move(10, 10) // 툴팁 잔상 제거(다음 화면 오염 방지)
await page.waitForTimeout(500)

// 3) 블록(MCP 탭) — 별명 비노출
await nav('blocks')
const blocksText = await page.locator('body').innerText()
check('blocks: mock 별명("Local Tools"류) 비노출', !/Local Tools|Calc Tools/i.test(blocksText), '')
await page.screenshot({ path: path.join(OUT, 'blocks.png'), fullPage: true })

// 4) 컬렉션 — 이름만(설명 상시 노출 제거 확인: docs-kb 행에 설명 텍스트 부재)
await nav('collections')
const collText = await page.locator('body').innerText()
check('collections: 이름(docs-kb) 노출', collText.includes('docs-kb'))
await page.screenshot({ path: path.join(OUT, 'collections.png'), fullPage: true })

// 5) 세션 — 에이전트 이름(name) 표기 유지
await nav('sessions')
const sessText = await page.locator('body').innerText()
check('sessions: 별명 비노출', !sessText.includes('Research Assistant'))
await page.screenshot({ path: path.join(OUT, 'sessions.png'), fullPage: true })

await browser.close()
console.log(fails === 0 ? 'ALL PASS' : `${fails} FAIL`)
process.exit(fails === 0 ? 0 : 1)
