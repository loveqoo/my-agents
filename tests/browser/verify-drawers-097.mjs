/* 스펙 097 검증 — 통합 후 두 드로어가 각 도메인 라벨·구조·동작으로 렌더되는가.
   컬렉션 docs_kb(ready) 검색 시험 + 에이전트 조회 시험 + 스코프 전환 리셋.
   antd6: 드로어 루트 = .ant-drawer.ant-drawer-open, 본문 = .ant-drawer-section. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(`${pwDir}/index.js`)
const chromium = _pw.chromium ?? _pw.default?.chromium
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
const DR = '.ant-drawer.ant-drawer-open'
const drawer = () => page.evaluate((sel) => {
  const d = document.querySelector(sel)
  if (!d) return null
  const txt = d.textContent.replace(/\s+/g, ' ')
  return {
    title: d.querySelector('.ant-drawer-title')?.textContent?.trim(),
    limitLabel: [...d.querySelectorAll('span')].map(s=>s.textContent.trim()).find(t=>/^(top_k|limit)/.test(t)) ?? null,
    runBtns: [...d.querySelectorAll('button')].map(b=>(b.textContent||'').trim()).filter(Boolean),
    scoreTags: [...d.querySelectorAll('.ant-tag')].map(t=>t.textContent.trim()).filter(t=>/유사도|관련도/.test(t)),
    query: d.querySelector('textarea')?.value ?? '',
    alertTitle: d.querySelector('.ant-alert-message')?.textContent?.trim() ?? null,
    countLine: /결과 \d+건|회상 \d+건/.exec(txt)?.[0] ?? null,
    emptyOrDisabled: /관련 청크를 찾지 못했습니다|회상된 기억이 없습니다|비활성\/미구성/.test(txt),
  }
}, DR)
const R = {}
try {
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('RAG 컬렉션', { exact: true }).first().waitFor({ timeout: 10000 })

  // ===== A. 컬렉션 검색 시험 =====
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.getByText('docs_kb', { exact: true }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: '검색' }).first().click() // loose(아이콘 때문)
  await page.locator(DR).waitFor({ timeout: 5000 })
  await page.waitForTimeout(400)
  R.collection_open = await drawer()
  await page.locator(`${DR} textarea`).fill('문서')
  await page.locator(DR).getByRole('button', { name: '검색' }).click()
  await page.waitForTimeout(1800)
  R.collection_result = await drawer()
  await page.screenshot({ path: '/tmp/097-A-collection.png' })
  await page.keyboard.press('Escape'); await page.waitForTimeout(500)

  // ===== B. 메모리 조회 시험 =====
  await page.getByText('메모리', { exact: true }).first().click()
  await page.waitForTimeout(900)
  const sel = page.locator('.ant-select').first()
  await sel.click(); await page.waitForTimeout(400)
  const firstAgent = page.locator('.ant-select-item-option').first()
  const agentName = (await firstAgent.textContent())?.trim()
  await firstAgent.click(); await page.waitForTimeout(900)
  await page.getByRole('button', { name: '조회 시험' }).first().click()
  await page.locator(DR).waitFor({ timeout: 5000 })
  await page.waitForTimeout(300)
  R.memory_open = { ...await drawer(), agent: agentName }
  await page.locator(`${DR} textarea`).fill('내 보고서 형식')
  await page.locator(DR).getByRole('button', { name: '조회' }).click()
  await page.waitForTimeout(1800)
  R.memory_result = await drawer()
  await page.screenshot({ path: '/tmp/097-B-memory.png' })

  // ===== C. 스코프 전환 리셋 =====
  await page.keyboard.press('Escape'); await page.waitForTimeout(500)
  await sel.click(); await page.waitForTimeout(400)
  const opts = page.locator('.ant-select-item-option')
  const n = await opts.count()
  await opts.nth(n > 1 ? 1 : 0).click()
  await page.waitForTimeout(900)
  await page.getByRole('button', { name: '조회 시험' }).first().click()
  await page.locator(DR).waitFor({ timeout: 5000 })
  await page.waitForTimeout(300)
  R.scope_reset = await drawer() // query가 빈 문자열이어야
} catch (e) { R.error = e?.message ?? String(e); process.exitCode = 1 }
finally { console.log(JSON.stringify(R, null, 1)); await browser.close() }
