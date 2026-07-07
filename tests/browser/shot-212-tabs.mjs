/* 스펙 212 검증 샷 — 탭 통일(승인=Tabs·세션=Segmented) + kind 분리(RAG 문서/엔티티 Tabs·평가 agent/rag Segmented).
   실행: PLAYWRIGHT_DIR=$PWD/tests/e2e/node_modules/playwright node tests/browser/shot-212-tabs.mjs */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { provisionSuper } from './_fixture.mjs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'out-212')
const BASE = process.env.ADMIN_URL || 'http://127.0.0.1:5173'
const { email, password } = provisionSuper()

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
let fails = 0
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
  if (!ok) fails++
}
const nav = async (key) => {
  await page.locator(`[data-menu-id$="${key}"]`).first().click({ timeout: 5000 })
  await page.waitForTimeout(1100)
}

await page.goto(BASE + '/')
await page.getByPlaceholder('you@example.com').fill(email)
await page.getByPlaceholder('비밀번호').fill(password)
await page.getByRole('button', { name: /로그인|login/i }).click()
await page.waitForTimeout(1500)

// 1) 승인 — antd Tabs(role=tab: 대기 중 / 처리됨)
await nav('approvals')
const apprTabs = await page.getByRole('tab').allInnerTexts()
check('승인: Tabs(대기 중/처리됨)', apprTabs.some((t) => /대기/.test(t)) && apprTabs.some((t) => /처리/.test(t)), JSON.stringify(apprTabs))
await page.screenshot({ path: path.join(OUT, 'approvals.png'), fullPage: true })

// 2) 세션 — Segmented(상태 필터), Radio 부재
await nav('sessions')
const seg = await page.locator('.ant-segmented').first().innerText().catch(() => '')
check('세션: Segmented 상태 필터', /전체/.test(seg) && /라이브/.test(seg), JSON.stringify(seg.replace(/\n/g, '|').slice(0, 60)))
check('세션: Radio 부재', (await page.locator('.ant-radio-group').count()) === 0)
await page.screenshot({ path: path.join(OUT, 'sessions.png'), fullPage: true })

// 3) RAG — Tabs(문서 임베딩 / 엔티티 임베딩)
await nav('collections')
const ragTabs = await page.getByRole('tab').allInnerTexts()
check('RAG: 문서/엔티티 Tabs', ragTabs.some((t) => /문서/.test(t)) && ragTabs.some((t) => /엔티티/.test(t)), JSON.stringify(ragTabs))
await page.screenshot({ path: path.join(OUT, 'rag-document.png'), fullPage: true })
// 엔티티 탭 전환
await page.getByRole('tab', { name: /엔티티/ }).click()
await page.waitForTimeout(800)
await page.screenshot({ path: path.join(OUT, 'rag-entity.png'), fullPage: true })

// 4) 평가 — 문제집 탭 안 Segmented(에이전트 평가 / RAG 평가)
await nav('eval')
await page.waitForTimeout(600)
const evalSeg = await page.locator('.ant-segmented').filter({ hasText: '평가' }).first().innerText().catch(() => '')
check('평가: kind Segmented(에이전트/RAG)', /에이전트 평가/.test(evalSeg) && /RAG 평가/.test(evalSeg), JSON.stringify(evalSeg.replace(/\n/g, '|')))
await page.screenshot({ path: path.join(OUT, 'eval-agent.png'), fullPage: true })
// RAG 평가로 전환
await page.locator('.ant-segmented-item', { hasText: 'RAG 평가' }).first().click()
await page.waitForTimeout(900)
await page.screenshot({ path: path.join(OUT, 'eval-rag.png'), fullPage: true })

await browser.close()
console.log(fails === 0 ? 'ALL PASS' : `${fails} FAIL`)
process.exit(fails === 0 ? 0 : 1)
